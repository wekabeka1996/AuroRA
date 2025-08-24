
import torch
import time
import numpy as np
import pandas as pd

# Імпортуємо всі наші компоненти
from models.dssm import DSSM
from models.router import RegimeRouter
from certification.icp import DynamicICP  # legacy
from living_latent.core.icp_dynamic import AdaptiveICP
from living_latent.core.icp_adapter import ICPAdapter
from living_latent.core.acceptance import Acceptance, AcceptanceCfg, Event  # acceptance layer
from living_latent.core.acceptance_hysteresis import HysteresisGate, HysteresisCfg
from living_latent.obs.metrics import Metrics
from living_latent.service.context import CTX  # unified API service context
try:
    from living_latent.service.api import create_app  # optional runtime app
except Exception:  # pragma: no cover
    create_app = None  # type: ignore
import threading
from certification.dro_es import DRO_ES
from certification.uncertainty import UncertaintyMetrics
from living_latent.state.snapshot import (
    make_icp_state, make_acceptance_state, load_icp_state, load_acceptance_state,
    save_snapshot, load_snapshot
)
from living_latent.execution.gating import RiskGate, GatingCfg, DecisionHysteresis, DwellConfig, apply_risk_scale

# Припускаємо, що конфігурація завантажується з одного місця
# from utils.config import load_config

class TradingSystem:
    """
    Повністю інтегрована торгова система, що об'єднує всі компоненти.
    """
    def __init__(self, config, acceptance: Acceptance | None = None):
        print("--- Initializing Trading System ---")
        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.latency_budget = self.config.get('trading', {}).get('max_latency_ms', 120.0)
        self.position = None  # Поточна позиція/ваги портфеля
        self.acceptance = acceptance  # may be None in early phases / dependency injection for tests
        self.metrics = None
    # autosave tracking
        self._last_autosave_ts = time.time()
        self._events_since_save = 0
        self.risk_gate: RiskGate | None = None

        # Завантажуємо та ініціалізуємо всі модулі
        self._load_models()
        self._init_certification()
        print("--- Trading System Initialized Successfully ---")

    def _load_models(self):
        import os
        cfg_model = self.config['student']
        self.student = DSSM(
            d_obs=cfg_model['d_obs'],
            d_latent=cfg_model['d_latent'],
            d_hidden=cfg_model['d_hidden']
        ).to(self.device)
        ckpt_s = cfg_model.get('checkpoint')
        if ckpt_s and os.path.exists(ckpt_s):
            state = torch.load(ckpt_s, map_location=self.device)
            missing, unexpected = self.student.load_state_dict(state, strict=False)
            print(f"DSSM Student model loaded (strict=False). Missing: {missing if missing else 'None'} | Unexpected: {unexpected if unexpected else 'None'}")
        else:
            print(f"[WARN] DSSM checkpoint not found: {ckpt_s}. Using randomly initialized weights.")
        self.student.eval()

        cfg_router = self.config['router']
        self.router = RegimeRouter(
            d_input=cfg_model['d_obs'], # Роутер приймає ті ж фічі, що і студент
            num_regimes=cfg_router['num_regimes']
        ).to(self.device)
        ckpt_r = cfg_router.get('checkpoint')
        if ckpt_r and os.path.exists(ckpt_r):
            state_r = torch.load(ckpt_r, map_location=self.device)
            miss_r, unexp_r = self.router.load_state_dict(state_r, strict=False)
            print(f"RegimeRouter model loaded (strict=False). Missing: {miss_r if miss_r else 'None'} | Unexpected: {unexp_r if unexp_r else 'None'}")
        else:
            print(f"[WARN] Router checkpoint not found: {ckpt_r}. Using randomly initialized weights.")
        self.router.eval()

    def _init_certification(self):
        cfg_cert = self.config['certification']
        # Feature flag path if governance master.yaml loaded
        use_adaptive = True
        try:
            gov_profile = self.config.get('governance_profile')  # e.g., 'default'
            if gov_profile:
                gov_cfg = self.config['governance'][gov_profile]
                use_adaptive = bool(gov_cfg.get('features', {}).get('use_adaptive_icp', True))
        except Exception:
            pass

        if use_adaptive:
            alpha_target = cfg_cert['icp'].get('alpha_base', 0.1)
            window = cfg_cert['icp'].get('window', 1000)
            eta = cfg_cert['icp'].get('eta', 0.01)
            self.icp_core = AdaptiveICP(alpha_target=alpha_target, eta=eta, window=window, quantile_mode='p2')
            self.icp = ICPAdapter(self.icp_core)
            print("[ICP] AdaptiveICP enabled via adapter.")
        else:
            self.icp = DynamicICP(**cfg_cert['icp'])
            print("[ICP] Legacy DynamicICP in use (feature flag disabled).")

        self.dro = DRO_ES(**cfg_cert['dro'])
        self.uncertainty = UncertaintyMetrics(**cfg_cert['uncertainty'])
        print("Certification components initialized.")
        # Governance profile wiring for acceptance + metrics + hysteresis
        try:
            gov_profile = self.config.get('governance_profile')
            if gov_profile and self.acceptance is None:  # only build if not injected
                prof = self.config['governance'][gov_profile]
                acc_prof = prof.get('acceptance', {})
                kap_prof = prof.get('kappa', {})
                m_prof = prof.get('metrics', {})
                # Metrics
                if m_prof.get('enabled', False):
                    buckets = dict(
                        latency_buckets_ms=m_prof.get('latency_buckets_ms', []),
                        surprisal_buckets=m_prof.get('surprisal_buckets', []),
                        width_buckets=m_prof.get('width_buckets', []),
                        kappa_buckets=m_prof.get('kappa_buckets', []),
                    )
                    self.metrics = Metrics(profile=gov_profile, buckets=buckets)
                    try:
                        self.metrics.start_http(int(m_prof.get('port', 9108)))
                    except Exception:
                        pass
                # Hysteresis gate (Acceptance internal gate)
                hys_cfg_raw = acc_prof.get('hysteresis', {})
                dwell_raw = acc_prof.get('dwell', {})
                gate = HysteresisGate(HysteresisCfg.from_dict(hys_cfg_raw, dwell_raw))
                # External decision hysteresis (AUR-GATE-601) to stabilize final decision stream
                try:
                    self.decision_hysteresis = DecisionHysteresis(
                        DwellConfig(
                            min_dwell_pass=int(dwell_raw.get('min_dwell_pass', 10)) if isinstance(dwell_raw, dict) else 10,
                            min_dwell_derisk=int(dwell_raw.get('min_dwell_derisk', 10)) if isinstance(dwell_raw, dict) else 10,
                            min_dwell_block=int(dwell_raw.get('min_dwell_block', 1)) if isinstance(dwell_raw, dict) else 1,
                        )
                    )
                except Exception:
                    self.decision_hysteresis = None
                # Acceptance config
                a_cfg = AcceptanceCfg(
                    tau_pass=kap_prof.get('tau_pass', 0.75),
                    tau_derisk=kap_prof.get('tau_derisk', 0.50),
                    coverage_lower_bound=acc_prof.get('coverage_lower_bound', 0.90),
                    surprisal_p95_guard=acc_prof.get('surprisal_p95_guard', 2.5),
                    latency_p95_max_ms=acc_prof.get('latency_p95_max_ms', 120.0),
                    max_interval_rel_width=acc_prof.get('max_interval_rel_width', 0.06),
                    persistence_n=acc_prof.get('persistence_n', 20),
                    penalties=acc_prof.get('penalties', {'latency_to_kappa_bonus': -0.05, 'coverage_deficit_bonus': -0.10}),
                    c_ref=kap_prof.get('c_ref', 0.01),
                    beta_ref=kap_prof.get('beta_ref', 0.0),
                    sigma_min=kap_prof.get('sigma_min', 1e-6),
                )
                self.acceptance = Acceptance(a_cfg, hysteresis_gate=gate, metrics=self.metrics, profile_label=gov_profile)
                # inject into unified service context
                try:
                    CTX.set_profile(gov_profile)
                    if self.metrics is not None:
                        CTX.set_registry(self.metrics.registry)
                    CTX.set_acceptance(self.acceptance)
                except Exception:
                    pass
                # Execution gating config (Batch-010)
                try:
                    exec_cfg = prof.get('execution', {}).get('gating', {})
                    if exec_cfg:
                        gcfg = GatingCfg(
                            scale_map=exec_cfg.get('scale_map', {'PASS':1.0,'DERISK':0.5,'BLOCK':0.0}),
                            hard_block_on_guard=exec_cfg.get('hard_block_on_guard', True),
                            min_notional=float(exec_cfg.get('min_notional', 0.0)),
                            max_notional=float(exec_cfg.get('max_notional', 1e12)),
                        )
                        self.base_notional = float(exec_cfg.get('base_notional', 1.0))
                        self.risk_gate = RiskGate(gcfg)
                except Exception as e:
                    print(f"[WARN] Execution gating init failed: {e}")
                # optional API start if configured (only if enabled and app factory present)
                try:
                    svc_cfg = prof.get('service', {}).get('api', {})
                    metrics_mode = prof.get('metrics', {}).get('mode', 'standalone')
                    if svc_cfg.get('enabled', False) and create_app is not None:
                        host = svc_cfg.get('host', '0.0.0.0')
                        port = int(svc_cfg.get('port', 9100))
                        app = create_app()
                        threading.Thread(target=lambda: __import__('uvicorn').run(app, host=host, port=port, log_level='warning'), daemon=True).start()
                        # ensure we did not start standalone metrics server when mode=='api'
                except Exception:
                    pass
        except Exception:
            pass

    # --- Допоміжні методи-заглушки ---
    def extract_features(self, market_data):
        """Конвертація в детермінований вектор фіч.

        Parameters
        ----------
        market_data : dict | pd.DataFrame
            Якщо dict очікуємо ключі open/high/low/close/volume (поточна свічка) +
            опційно історію під ключем 'history' (DataFrame) для індикаторів.
            Якщо DataFrame — беремо як історію й останній рядок як поточний.

        Returns
        -------
        torch.Tensor shape (1, d_obs)
        """
        try:  # lazy import (щоб уникнути циклів)
            from data_pipeline.features import build_features, feature_vector
        except Exception as e:  # pragma: no cover
            print(f"[WARN] feature module import failed: {e}; fallback random")
            return torch.randn(1, self.config['student']['d_obs']).to(self.device)

        if isinstance(market_data, pd.DataFrame):
            hist_df = market_data.copy()
        else:
            # Expect dict
            history = market_data.get('history') if isinstance(market_data, dict) else None
            if history is None:
                # Build minimal DF from single point (warm-up); duplicate row to avoid zero windows
                row = {k: float(market_data[k]) for k in ['open','high','low','close','volume']}
                hist_df = pd.DataFrame([row, row])
            else:
                hist_df = history.copy()
                # Append current point if newer
                if isinstance(market_data, dict) and all(k in market_data for k in ['open','high','low','close','volume']):
                    ts = getattr(hist_df.index, 'tz_localize', lambda _: hist_df.index)(None)
                    # Append with next incremental index if needed
                    try:
                        next_idx = hist_df.index[-1] + (hist_df.index[-1] - hist_df.index[-2])
                    except Exception:
                        next_idx = hist_df.index[-1]
                    new_row = {k: float(market_data[k]) for k in ['open','high','low','close','volume']}
                    hist_df.loc[next_idx] = new_row

        try:
            full = build_features(hist_df)
            # Take the last row (current time)
            last = full.iloc[-1:]
            # Ensure ordering matches d_obs expectation; derive once
            if not hasattr(self, '_feature_order'):
                base_exclude = {'open','high','low','close','volume'}
                candidates = [c for c in last.columns if c not in base_exclude]
                # Sort for stability
                self._feature_order = sorted(candidates)[:self.config['student']['d_obs']]
            vec = last[self._feature_order].to_numpy(dtype=np.float32)
            # If fewer features than d_obs pad with zeros (rare initial warm-up)
            d_obs = self.config['student']['d_obs']
            if vec.shape[1] < d_obs:
                pad = np.zeros((1, d_obs - vec.shape[1]), dtype=np.float32)
                vec = np.concatenate([vec, pad], axis=1)
        except Exception as e:
            print(f"[WARN] feature extraction failed ({e}); fallback random")
            vec = np.random.randn(1, self.config['student']['d_obs']).astype(np.float32)
        return torch.from_numpy(vec).to(self.device)

    def compute_aci(self, z, regime_probs):
        """ЗАГЛУШКА: Розрахунок ARMA Crossbar Index (ACI)."""
        # ACI вимірює нестабільність моделі
        return np.random.uniform(0, 1.5)

    def _should_rebalance(self, kappa_plus):
        """ЗАГЛУШКА: Вирішує, чи потрібно перебалансовувати портфель."""
        # Перебалансування, якщо невизначеність висока або позиції немає
        rebalance_threshold = self.config['trading'].get('rebalance_threshold', 0.7)
        return self.position is None or kappa_plus > rebalance_threshold

    def generate_scenarios(self, z, regime):
        """ЗАГЛУШКА: Генерує сценарії для DRO-ES оптимізатора."""
        # Сценарії можуть бути згенеровані вчителем (NFSDE) або іншим методом
        n_scenarios = 512
        d_assets = 5 # Припустимо, 5 активів у портфелі
        return np.random.randn(n_scenarios, d_assets) * (regime.item() + 1) * 0.01

    @torch.no_grad()
    def predict(self, market_data):
        """Основний цикл прогнозування та прийняття рішень."""
        start_time = time.perf_counter()
        
        # 1. Feature extraction (5ms budget)
        features = self.extract_features(market_data)
        
        # 2. Regime detection (10ms budget)
        regime_probs, _ = self.router(features)
        regime = torch.argmax(regime_probs, dim=-1)
        
        # 3. Student inference (30ms budget)
        # У реальному часі ми б хотіли лише один крок
        _, z, _ = self.student(features.unsqueeze(1))  # seq_len=1
        z = z.squeeze(1)  # (batch=1, d_latent)
        y_hat, sigma_hat = self.student.decode(z)  # ожидаем (1, d_obs) оба
        # Преобразуем к скалярам: берем главный таргет по последнему каналу или среднее
        # Допущение: первый столбец соответствует основному прогнозу
        if y_hat.dim() == 2:
            y_hat_scalar = y_hat[0, 0]
        else:
            y_hat_scalar = y_hat.squeeze()

        if sigma_hat.dim() == 2:
            sigma_hat_scalar = sigma_hat[0, 0]
        else:
            sigma_hat_scalar = sigma_hat.squeeze()

        y_hat, sigma_hat = float(y_hat_scalar.detach().cpu().item()), float(sigma_hat_scalar.detach().cpu().item())

        # 4. ACI calculation (5ms budget)
        aci = self.compute_aci(z, regime_probs)
        
        # 5. Certification (20ms budget)
        # ICP interval depending on implementation
        if isinstance(self.icp, ICPAdapter):
            lower, upper = self.icp.predict(y_hat, sigma_hat)
            alpha = getattr(self.icp.icp, 'alpha', None)
        else:  # legacy DynamicICP
            lower, upper, alpha = self.icp.predict_interval(y_hat, sigma_hat, z, aci)
        
        # 6. Uncertainty (10ms budget)
        kappa = self.uncertainty.compute_kappa(z, regime_probs, upper - lower, {'sigma': sigma_hat})
        kappa_plus = self.uncertainty.compute_kappa_plus(kappa, lower, upper)
        
        # 7. Portfolio optimization (15ms budget)
        if self._should_rebalance(kappa_plus):
            print("[INFO] Rebalance condition met. Running DRO-ES optimizer...")
            scenarios = self.generate_scenarios(z, regime)
            weights, cvar = self.dro.optimize(scenarios, regime, aci)
            self.position = weights
        else:
            weights = self.position
            
        # 8. Latency check (5ms buffer)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if elapsed_ms > self.latency_budget:
            print(f"[WARNING] Latency budget exceeded: {elapsed_ms:.1f}ms")
        
        out = {
            'forecast': y_hat,
            'interval': (lower, upper),
            'weights': weights,
            'kappa_plus': kappa_plus,
            'regime': regime.item(),
            'aci': aci,
            'latency_ms': elapsed_ms
        }
        # --- Acceptance decision hook (advisory only, no side-effects) ---
        if self.acceptance is not None:
            evt = Event(
                ts=time.time(),
                mu=y_hat,
                sigma=sigma_hat,
                interval=(lower, upper),
                latency_ms=elapsed_ms,
                y=None
            )
            decision_raw, info = self.acceptance.decide(evt)
            # Apply external hysteresis wrapper if configured
            if hasattr(self, 'decision_hysteresis') and self.decision_hysteresis is not None:
                decision = self.decision_hysteresis.update(decision_raw)
                if self.metrics is not None:
                    try:
                        self.metrics.set_decision_churn(self.decision_hysteresis.churn_per_1k())
                        # dwell efficiency gauge
                        if hasattr(self.decision_hysteresis, 'dwell_efficiency'):
                            self.metrics.set_dwell_efficiency(self.decision_hysteresis.dwell_efficiency())
                    except Exception:
                        pass
            else:
                decision = decision_raw
            out['acceptance_decision'] = decision
            out['acceptance_info'] = info
            # --- Execution Risk Gate (scaling) ---
            if self.risk_gate is not None:
                # extract guard booleans (no explicit flags exposed, derive from info + thresholds)
                try:
                    prof = self.config.get('governance_profile')
                    acc_cfg = self.config.get('governance', {}).get(prof, {}).get('acceptance', {}) if prof else {}
                    guard_surprisal = False
                    guard_latency = False
                    guard_coverage = False
                    guard_width = False
                    if isinstance(info, dict):
                        p95_s = info.get('p95_surprisal')
                        if p95_s is not None and not np.isnan(p95_s):
                            guard_surprisal = p95_s > acc_cfg.get('surprisal_p95_guard', float('inf'))
                        lat_p95 = info.get('latency_p95')
                        if lat_p95 is not None and not np.isnan(lat_p95):
                            guard_latency = lat_p95 > acc_cfg.get('latency_p95_max_ms', float('inf'))
                        cov_ema = info.get('coverage_ema')
                        if cov_ema is not None and not np.isnan(cov_ema):
                            guard_coverage = cov_ema < acc_cfg.get('coverage_lower_bound', -float('inf'))
                        rel_w = info.get('rel_width')
                        if rel_w is not None and not np.isnan(rel_w):
                            guard_width = rel_w > acc_cfg.get('max_interval_rel_width', float('inf'))
                    guards = {
                        'surprisal': guard_surprisal,
                        'latency': guard_latency,
                        'coverage': guard_coverage,
                        'width': guard_width,
                    }
                except Exception:
                    guards = {'surprisal': False,'latency': False,'coverage': False,'width': False}
                notional_reco = self.risk_gate.scale(decision, guards, getattr(self, 'base_notional', 1.0))
                risk_scale = 0.0 if getattr(self, 'base_notional', 1.0) == 0 else notional_reco / getattr(self, 'base_notional', 1.0)
                # Final applied notional (post external risk_scale; apply_risk_scale ensures clipping & safety)
                out['risk_scale'] = risk_scale
                out['notional_reco'] = notional_reco
                out['notional_applied'] = apply_risk_scale(getattr(self, 'base_notional', 1.0), risk_scale)
                out['execution_guards'] = guards
                if self.metrics is not None:
                    try:
                        self.metrics.set_execution_risk_scale(risk_scale)
                        if notional_reco == 0.0:
                            # choose reason precedence order
                            reason = 'guard' if any(guards.values()) else ('decision' if decision=='BLOCK' else 'other')
                            self.metrics.count_execution_block(reason)
                    except Exception:
                        pass
        return out

    def on_observation(self, y: float, last_prediction: dict):
        """Update ICP & Acceptance with realized observation.

        Parameters
        ----------
        y : float
            Realized target value.
        last_prediction : dict
            Output dict from predict() containing 'forecast','interval','latency_ms'.
        """
        try:
            mu = float(last_prediction['forecast'])
            lo, hi = last_prediction['interval']
            latency = last_prediction.get('latency_ms')
        except Exception:
            return
        # Adaptive ICP update if present
        try:
            if hasattr(self, 'icp_core'):
                # Need sigma; attempt infer from interval width / 2q ~ margin. Approx sigma from interval
                lo, hi = last_prediction['interval']
                est_sigma = max(1e-9, (hi - lo) / 6)  # rough heuristic if q≈3
                self.icp_core.update(y, mu, est_sigma)
        except Exception:
            pass
        if self.acceptance is not None:
            evt = Event(
                ts=time.time(),
                mu=mu,
                sigma=0.0,  # TODO: supply sigma if available from decode
                interval=(lo, hi),
                latency_ms=latency,
                y=y
            )
            self.acceptance.update(evt)
            # propagate ICP stats (adaptive only)
            try:
                if hasattr(self, 'icp_core') and self.metrics is not None:
                    st = self.icp_core.stats()
                    alpha = getattr(st, 'alpha', getattr(self.icp_core, 'alpha', None))
                    alpha_target = getattr(self.icp_core, 'alpha_target', self.icp_core.alpha_target)
                    cov_ema = getattr(st, 'coverage_ema', float('nan'))
                    if alpha is not None:
                        self.acceptance.set_icp_stats(alpha=float(alpha), alpha_target=float(alpha_target), coverage_ema=float(cov_ema))
            except Exception:
                pass
        # autosave trigger
        try:
            state_cfg = None
            prof = self.config.get('governance_profile')
            if prof:
                state_cfg = self.config.get('governance', {}).get(prof, {}).get('state')
            if state_cfg and state_cfg.get('enabled', False):
                self._events_since_save += 1
                autos = state_cfg.get('autosave', {})
                ev_thr = autos.get('every_events') or None
                sec_thr = autos.get('every_seconds') or None
                jitter = autos.get('jitter_seconds', 0)
                now = time.time()
                due_events = ev_thr is not None and self._events_since_save >= ev_thr
                due_time = sec_thr is not None and (now - self._last_autosave_ts) >= (sec_thr + (jitter * 0.5))
                if due_events or due_time:
                    path = state_cfg.get('snapshot_path', 'snapshot.json')
                    self.save_state(path)
                    self._events_since_save = 0
                    self._last_autosave_ts = now
        except Exception:
            pass

    # ---------------- Persistence API (Batch-009) ---------------- #
    def save_state(self, path: str):
        """Serialize ICP + Acceptance FSM state to JSON snapshot.

        Parameters
        ----------
        path : str
            Target file path. Atomic replace semantics.
        """
        try:
            icp_payload = make_icp_state(getattr(self, 'icp_core', None) or getattr(self, 'icp', None))
            acc_payload = make_acceptance_state(self.acceptance) if self.acceptance is not None else {}
            save_snapshot(path, icp_payload, acc_payload)
        except Exception as e:
            print(f"[WARN] save_state failed: {e}")

    def load_state(self, path: str):
        """Restore ICP + Acceptance FSM state from snapshot if file exists."""
        try:
            icp_payload, acc_payload = load_snapshot(path)
        except FileNotFoundError:
            print(f"[INFO] Snapshot not found: {path}")
            return
        except Exception as e:
            print(f"[WARN] load_state read error: {e}")
            return
        try:
            core = getattr(self, 'icp_core', None) or getattr(self, 'icp', None)
            if core is not None:
                load_icp_state(core, icp_payload)
        except Exception as e:
            print(f"[WARN] load_state icp restore failed: {e}")
        try:
            if self.acceptance is not None:
                load_acceptance_state(self.acceptance, acc_payload)
        except Exception as e:
            print(f"[WARN] load_state acceptance restore failed: {e}")