import React, { useState, useEffect, useCallback } from 'react';
import { Activity, Circle, TrendingUp, BarChart3, Zap, AlertTriangle, Wifi, WifiOff } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const TELEMETRY_URL = process.env.REACT_APP_TELEMETRY_URL || 'http://localhost:8001';
const RECONNECT_TIMEOUT = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

function App() {
  const [connectionStatus, setConnectionStatus] = useState('disconnected');
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [lastEventId, setLastEventId] = useState(null);
  const [eventSource, setEventSource] = useState(null);
  const [showReconnectBanner, setShowReconnectBanner] = useState(false);
  const [metrics, setMetrics] = useState({
    orders: {
      submitted: 0,
      acknowledged: 0,
      filled: 0,
      cancelled: 0,
      denied: 0,
      failed: 0
    },
    routes: {
      maker: 0,
      taker: 0,
      deny: 0,
      cancel: 0
    },
    latency: {
      p50: 0,
      p90: 0,
      p99: 0
    },
    governance: {
      alpha_score: 0,
      sprt_ratio: 0,
      decisions_count: 0
    },
    xai: {},
    circuit_breaker: {
      triggered: false,
      reason: null
    },
    pending: 0
  });
  
  const [latencyHistory, setLatencyHistory] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);

  const connectToFeed = useCallback(() => {
    // Close existing connection
    if (eventSource) {
      eventSource.close();
    }
    
    // Build SSE URL with Last-Event-ID if available
    let url = `${TELEMETRY_URL}/sse`;
    const headers = {};
    if (lastEventId) {
      headers['Last-Event-ID'] = lastEventId;
    }
    
    const newEventSource = new EventSource(url);
    setEventSource(newEventSource);
    
    newEventSource.onopen = () => {
      setConnectionStatus('connected');
      setReconnectAttempts(0);
      setShowReconnectBanner(false);
      console.log('Connected to live feed');
    };
    
    newEventSource.onmessage = (event) => {
      try {
        // Store event ID for reconnection
        if (event.lastEventId) {
          setLastEventId(event.lastEventId);
        }
        
        const data = JSON.parse(event.data);
        setMetrics(data);
        setLastUpdate(new Date());
        
        // Update latency history for chart
        setLatencyHistory(prev => {
          const newPoint = {
            time: new Date().toLocaleTimeString(),
            p50: data.latency?.decision_ms_p50 || 0,
            p90: data.latency?.decision_ms_p90 || 0,
            p99: data.latency?.to_first_fill_ms_p90 || 0
          };
          return [...prev.slice(-19), newPoint]; // Keep last 20 points
        });
      } catch (error) {
        console.error('Error parsing SSE data:', error);
      }
    };
    
    newEventSource.onerror = () => {
      setConnectionStatus('disconnected');
      setShowReconnectBanner(true);
      console.error('SSE connection error');
      
      // Auto-reconnect with exponential backoff
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        const timeout = Math.min(RECONNECT_TIMEOUT * Math.pow(1.5, reconnectAttempts), 30000);
        setTimeout(() => {
          setReconnectAttempts(prev => prev + 1);
          setConnectionStatus('connecting');
          connectToFeed();
        }, timeout);
      }
    };
    
    return newEventSource;
  }, [eventSource, lastEventId, reconnectAttempts]);

  useEffect(() => {
    setConnectionStatus('connecting');
    const es = connectToFeed();
    
    return () => {
      if (es) {
        es.close();
      }
    };
  }, [connectToFeed]);

  const manualReconnect = () => {
    setReconnectAttempts(0);
    setConnectionStatus('connecting');
    connectToFeed();
  };

  const getConnectionStatusIcon = () => {
    switch (connectionStatus) {
      case 'connected': return <Circle className="w-3 h-3 fill-current" />;
      case 'connecting': return <Activity className="w-4 h-4 animate-pulse" />;
      default: return <Circle className="w-3 h-3" />;
    }
  };

  const getStatusText = () => {
    switch (connectionStatus) {
      case 'connected': return 'Live';
      case 'connecting': return 'Connecting...';
      default: return 'Disconnected';
    }
  };

  const formatLatency = (ms) => `${ms.toFixed(1)}ms`;
  
  const orderFillRate = metrics.orders.submitted > 0 
    ? ((metrics.orders.filled / metrics.orders.submitted) * 100).toFixed(1)
    : '0.0';

  const takerRate = (metrics.routes.maker + metrics.routes.taker) > 0
    ? ((metrics.routes.taker / (metrics.routes.maker + metrics.routes.taker)) * 100).toFixed(1)
    : '0.0';

  return (
    <div className="dashboard">
      {/* Reconnection Banner */}
      {showReconnectBanner && connectionStatus === 'disconnected' && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          backgroundColor: '#ef4444',
          color: 'white',
          padding: '10px',
          textAlign: 'center',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '10px'
        }}>
          <WifiOff className="w-5 h-5" />
          Connection lost. 
          {reconnectAttempts < MAX_RECONNECT_ATTEMPTS ? (
            <span>Reconnecting... (attempt {reconnectAttempts + 1}/{MAX_RECONNECT_ATTEMPTS})</span>
          ) : (
            <button 
              onClick={manualReconnect}
              style={{
                background: 'rgba(255,255,255,0.2)', 
                border: '1px solid white', 
                color: 'white', 
                padding: '5px 10px', 
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              Retry Connection
            </button>
          )}
        </div>
      )}

      <div className="dashboard-header" style={{marginTop: showReconnectBanner ? '60px' : '0'}}>
        <h1 className="dashboard-title">
          <Activity className="inline w-8 h-8 mr-3" />
          Aurora Live Dashboard
        </h1>
        <div className={`connection-status status-${connectionStatus}`}>
          {getConnectionStatusIcon()}
          {getStatusText()}
          {reconnectAttempts > 0 && connectionStatus === 'connecting' && (
            <span style={{marginLeft: '8px', fontSize: '0.8rem'}}>
              (attempt {reconnectAttempts})
            </span>
          )}
        </div>
      </div>

      <div className="dashboard-grid">
        {/* Orders Overview */}
        <div className="metric-card">
          <h3><BarChart3 className="inline w-5 h-5 mr-2" />Orders</h3>
          <div className="metric-grid">
            <div className="metric-item">
              <div className="metric-label">Submitted</div>
              <div className="metric-value" style={{color: '#3b82f6'}}>{metrics.orders.submitted}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Filled</div>
              <div className="metric-value" style={{color: '#10b981'}}>{metrics.orders.filled}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Cancelled</div>
              <div className="metric-value" style={{color: '#f59e0b'}}>{metrics.orders.cancelled}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Failed</div>
              <div className="metric-value" style={{color: '#ef4444'}}>{metrics.orders.failed}</div>
            </div>
          </div>
          <div style={{textAlign: 'center', marginTop: '15px'}}>
            <div className="metric-label">Fill Rate</div>
            <div className="metric-value" style={{color: '#10b981', fontSize: '1.5rem'}}>{orderFillRate}%</div>
          </div>
        </div>

        {/* Routes Performance */}
        <div className="metric-card">
          <h3><TrendingUp className="inline w-5 h-5 mr-2" />Routes</h3>
          <div className="metric-grid">
            <div className="metric-item">
              <div className="metric-label">Maker</div>
              <div className="metric-value" style={{color: '#10b981'}}>{metrics.routes.maker}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Taker</div>
              <div className="metric-value" style={{color: '#f59e0b'}}>{metrics.routes.taker}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Denied</div>
              <div className="metric-value" style={{color: '#ef4444'}}>{metrics.routes.deny}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Cancelled</div>
              <div className="metric-value" style={{color: '#6b7280'}}>{metrics.routes.cancel}</div>
            </div>
          </div>
          <div style={{textAlign: 'center', marginTop: '15px'}}>
            <div className="metric-label">Taker Rate</div>
            <div className="metric-value" style={{color: '#f59e0b', fontSize: '1.5rem'}}>{takerRate}%</div>
          </div>
        </div>

        {/* Latency Metrics */}
        <div className="metric-card">
          <h3><Zap className="inline w-5 h-5 mr-2" />Latency</h3>
          <div className="metric-grid">
            <div className="metric-item">
              <div className="metric-label">Decision P50</div>
              <div className="metric-value" style={{color: '#10b981'}}>{formatLatency(metrics.latency?.decision_ms_p50 || 0)}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Decision P90</div>
              <div className="metric-value" style={{color: '#f59e0b'}}>{formatLatency(metrics.latency?.decision_ms_p90 || 0)}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Fill P50</div>
              <div className="metric-value" style={{color: '#10b981'}}>{formatLatency(metrics.latency?.to_first_fill_ms_p50 || 0)}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Fill P90</div>
              <div className="metric-value" style={{color: '#ef4444'}}>{formatLatency(metrics.latency?.to_first_fill_ms_p90 || 0)}</div>
            </div>
          </div>
        </div>

        {/* Governance */}
        <div className="metric-card">
          <h3><AlertTriangle className="inline w-5 h-5 mr-2" />Governance</h3>
          <div className="metric-grid">
            <div className="metric-item">
              <div className="metric-label">Alpha Score</div>
              <div className="metric-value" style={{color: '#00d4aa'}}>{(metrics.governance?.alpha?.score || 0).toFixed(3)}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">SPRT Ratio</div>
              <div className="metric-value" style={{color: '#8b5cf6'}}>{(metrics.governance?.sprt?.final?.ratio || 0).toFixed(2)}</div>
            </div>
          </div>
          <div style={{textAlign: 'center', marginTop: '15px'}}>
            <div className="metric-label">SPRT Updates</div>
            <div className="metric-value" style={{color: '#3b82f6', fontSize: '1.5rem'}}>{metrics.governance?.sprt?.updates || 0}</div>
          </div>
          
          {metrics.circuit_breaker?.triggered && (
            <div style={{
              marginTop: '15px',
              padding: '10px',
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '8px',
              textAlign: 'center'
            }}>
              <div style={{color: '#ef4444', fontWeight: 'bold'}}>🔴 Circuit Breaker</div>
              <div style={{fontSize: '0.9rem', color: '#ef4444'}}>{metrics.circuit_breaker.reason}</div>
            </div>
          )}
        </div>

        {/* Latency Chart */}
        <div className="metric-card" style={{gridColumn: 'span 2'}}>
          <h3>Latency Trends</h3>
          <div className="latency-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={latencyHistory}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="time" stroke="#888" />
                <YAxis stroke="#888" />
                <Tooltip 
                  contentStyle={{
                    backgroundColor: '#1a1a2e',
                    border: '1px solid #333',
                    borderRadius: '8px'
                  }}
                />
                <Line type="monotone" dataKey="p50" stroke="#10b981" strokeWidth={2} dot={false} name="P50" />
                <Line type="monotone" dataKey="p90" stroke="#f59e0b" strokeWidth={2} dot={false} name="P90" />
                <Line type="monotone" dataKey="p99" stroke="#ef4444" strokeWidth={2} dot={false} name="P99" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {lastUpdate && (
        <div className="last-updated">
          Last updated: {lastUpdate.toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}

export default App;