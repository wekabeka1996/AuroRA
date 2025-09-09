#!/usr/bin/env python3
"""
Aurora — Binance Capabilities Dump Tool
=======================================

Fetches and dumps Binance exchange capabilities at runtime:
- exchangeInfo: Trading rules, symbols, filters
- leverageBrackets: Leverage tiers for futures
- positionInformation: Current position details
- accountConfig: Account configuration and settings

Outputs structured JSON to artifacts/capabilities/ for compliance verification.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import ccxt
except ImportError:
    print("ERROR: ccxt library not found. Install with: pip install ccxt")
    sys.exit(1)


class BinanceCapabilitiesDumper:
    """Fetches and structures Binance exchange capabilities."""

    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.exchange = None
        self.capabilities = {}

    def _create_exchange(self) -> ccxt.Exchange:
        """Create CCXT Binance exchange instance."""
        exchange_class = ccxt.binance
        config = {
            'apiKey': os.getenv('BINANCE_API_KEY', ''),
            'secret': os.getenv('BINANCE_SECRET', ''),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',  # Use futures by default
            }
        }

        if self.testnet:
            config['urls'] = {
                'api': {
                    'public': 'https://testnet.binancefuture.com/fapi/v1',
                    'private': 'https://testnet.binancefuture.com/fapi/v1',
                }
            }

        return exchange_class(config)

    def fetch_exchange_info(self) -> Dict[str, Any]:
        """Fetch exchange trading rules and symbol information."""
        try:
            print("📡 Fetching exchangeInfo...")
            info = self.exchange.public_get_exchangeinfo()
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'exchangeInfo',
                'data': info
            }
        except Exception as e:
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'exchangeInfo',
                'error': str(e),
                'data': None
            }

    def fetch_leverage_brackets(self) -> Dict[str, Any]:
        """Fetch leverage brackets for futures symbols."""
        try:
            print("📡 Fetching leverageBrackets...")
            brackets = self.exchange.fapiPrivate_get_leveragebracket()
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'leverageBrackets',
                'data': brackets
            }
        except Exception as e:
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'leverageBrackets',
                'error': str(e),
                'data': None
            }

    def fetch_position_information(self) -> Dict[str, Any]:
        """Fetch current position information."""
        try:
            print("📡 Fetching positionInformation...")
            positions = self.exchange.fapiPrivate_get_positionrisk()
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'positionInformation',
                'data': positions
            }
        except Exception as e:
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'positionInformation',
                'error': str(e),
                'data': None
            }

    def fetch_account_config(self) -> Dict[str, Any]:
        """Fetch account configuration."""
        try:
            print("📡 Fetching account configuration...")
            account = self.exchange.fapiPrivate_get_account()
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'accountConfig',
                'data': account
            }
        except Exception as e:
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'endpoint': 'accountConfig',
                'error': str(e),
                'data': None
            }

    def dump_capabilities(self) -> Dict[str, Any]:
        """Fetch all capabilities and return structured data."""
        print(f"🔗 Connecting to Binance {'Testnet' if self.testnet else 'Production'}...")

        try:
            self.exchange = self._create_exchange()
            self.exchange.load_markets()

            capabilities = {
                'metadata': {
                    'exchange': 'binance',
                    'environment': 'testnet' if self.testnet else 'production',
                    'fetched_at': datetime.utcnow().isoformat(),
                    'ccxt_version': ccxt.__version__,
                    'api_credentials_configured': bool(
                        os.getenv('BINANCE_API_KEY') and os.getenv('BINANCE_SECRET')
                    )
                },
                'capabilities': {}
            }

            # Fetch all capability data
            capabilities['capabilities']['exchangeInfo'] = self.fetch_exchange_info()
            capabilities['capabilities']['leverageBrackets'] = self.fetch_leverage_brackets()
            capabilities['capabilities']['positionInformation'] = self.fetch_position_information()
            capabilities['capabilities']['accountConfig'] = self.fetch_account_config()

            self.capabilities = capabilities
            return capabilities

        except Exception as e:
            print(f"❌ Error connecting to exchange: {e}")
            return {
                'metadata': {
                    'exchange': 'binance',
                    'environment': 'testnet' if self.testnet else 'production',
                    'fetched_at': datetime.utcnow().isoformat(),
                    'error': str(e)
                },
                'capabilities': {}
            }

    def save_to_file(self, output_dir: str = "artifacts/capabilities") -> str:
        """Save capabilities to JSON file."""
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        env = "testnet" if self.testnet else "production"
        filename = f"binance_capabilities_{env}_{timestamp}.json"
        filepath = Path(output_dir) / filename

        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.capabilities, f, indent=2, ensure_ascii=False)

        print(f"💾 Saved capabilities to: {filepath}")
        return str(filepath)

    def generate_summary_report(self) -> str:
        """Generate a human-readable summary of capabilities."""
        if not self.capabilities:
            return "No capabilities data available."

        lines = []
        lines.append("# Binance Capabilities Snapshot")
        lines.append("")

        meta = self.capabilities.get('metadata', {})
        lines.append(f"**Exchange**: {meta.get('exchange', 'unknown')}")
        lines.append(f"**Environment**: {meta.get('environment', 'unknown')}")
        lines.append(f"**Fetched At**: {meta.get('fetched_at', 'unknown')}")
        lines.append(f"**CCXT Version**: {meta.get('ccxt_version', 'unknown')}")
        lines.append(f"**API Credentials**: {'✅ Configured' if meta.get('api_credentials_configured') else '❌ Missing'}")
        lines.append("")

        caps = self.capabilities.get('capabilities', {})

        # Exchange Info Summary
        lines.append("## Exchange Information")
        exch_info = caps.get('exchangeInfo', {})
        if exch_info.get('data'):
            data = exch_info['data']
            symbols = data.get('symbols', [])
            lines.append(f"- **Total Symbols**: {len(symbols)}")
            lines.append(f"- **Futures Symbols**: {len([s for s in symbols if s.get('contractType') == 'PERPETUAL'])}")
            lines.append(f"- **Server Time**: {data.get('serverTime', 'unknown')}")
        else:
            lines.append("- ❌ Failed to fetch exchange info")
        lines.append("")

        # Leverage Brackets Summary
        lines.append("## Leverage Brackets")
        lev_brackets = caps.get('leverageBrackets', {})
        if lev_brackets.get('data'):
            brackets = lev_brackets['data']
            lines.append(f"- **Symbols with Brackets**: {len(brackets)}")
            if brackets:
                sample = brackets[0]
                lines.append(f"- **Sample Symbol**: {sample.get('symbol', 'unknown')}")
                lines.append(f"- **Max Leverage**: {sample.get('brackets', [{}])[0].get('initialLeverage', 'unknown')}")
        else:
            lines.append("- ❌ Failed to fetch leverage brackets")
        lines.append("")

        # Position Information Summary
        lines.append("## Position Information")
        pos_info = caps.get('positionInformation', {})
        if pos_info.get('data'):
            positions = pos_info['data']
            lines.append(f"- **Total Positions**: {len(positions)}")
            open_positions = [p for p in positions if float(p.get('positionAmt', 0)) != 0]
            lines.append(f"- **Open Positions**: {len(open_positions)}")
        else:
            lines.append("- ❌ Failed to fetch position information")
        lines.append("")

        # Account Config Summary
        lines.append("## Account Configuration")
        acc_config = caps.get('accountConfig', {})
        if acc_config.get('data'):
            data = acc_config['data']
            lines.append(f"- **Account Type**: {data.get('accountType', 'unknown')}")
            lines.append(f"- **Can Trade**: {data.get('canTrade', 'unknown')}")
            lines.append(f"- **Can Deposit**: {data.get('canDeposit', 'unknown')}")
            lines.append(f"- **Can Withdraw**: {data.get('canWithdraw', 'unknown')}")
            assets = data.get('assets', [])
            lines.append(f"- **Assets Count**: {len(assets)}")
        else:
            lines.append("- ❌ Failed to fetch account configuration")
        lines.append("")

        return "\n".join(lines)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Dump Binance exchange capabilities")
    parser.add_argument('--production', action='store_true',
                       help='Use production instead of testnet')
    parser.add_argument('--output-dir', default='artifacts/capabilities',
                       help='Output directory for JSON files')
    parser.add_argument('--summary-only', action='store_true',
                       help='Only generate summary report, do not save files')

    args = parser.parse_args()

    # Create dumper
    dumper = BinanceCapabilitiesDumper(testnet=not args.production)

    # Fetch capabilities
    capabilities = dumper.dump_capabilities()

    # Generate and print summary
    summary = dumper.generate_summary_report()
    print("\n" + "="*60)
    print(summary)
    print("="*60)

    # Save to file unless summary-only
    if not args.summary_only:
        filepath = dumper.save_to_file(args.output_dir)
        print(f"\n📄 Summary also saved to: docs/BINANCE_CAPS_SNAPSHOT.md")

        # Also save summary to docs
        summary_path = Path("docs/BINANCE_CAPS_SNAPSHOT.md")
        summary_path.parent.mkdir(exist_ok=True)
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary)
        print(f"📄 Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()