import React, { useState } from 'react'
import {
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  History,
  Info,
  ShieldAlert,
  Wallet,
  X,
} from 'lucide-react'
import type { RecommendationCardData } from '@/types/recommendation'
import { StrikeVisualizer } from './StrikeVisualizer'

interface RecommendationsCardProps {
  data: RecommendationCardData
}

export const RecommendationsCard: React.FC<RecommendationsCardProps> = ({ data }) => {
  const [showUpdatesModal, setShowUpdatesModal] = useState(false)

  const formatINR = (val?: number) => {
    if (val === undefined || val === null || !Number.isFinite(val)) return '—'
    return `₹${val.toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`
  }

  const statusToneClass =
    data.status === 'BEARISH'
      ? 'status-bearish'
      : data.status === 'BULLISH'
      ? 'status-bullish'
      : 'status-neutral'

  return (
    <div className="recommendation-card-wrapper">
      <div className="recommendation-card">
        {/* ===================================================================
            1. HEADER SECTION (Purple / Blue Vibrant Gradient)
           =================================================================== */}
        <div className="card-header-gradient">
          <div className="header-meta-row">
            <div className="timestamp-badge">
              <Clock className="icon-tiny" />
              <span>{data.timestamp}</span>
            </div>

            <div className={`status-badge ${statusToneClass}`}>
              {data.status === 'BEARISH' && <ArrowDownRight className="icon-tiny" />}
              {data.status === 'BULLISH' && <ArrowUpRight className="icon-tiny" />}
              {data.status === 'NEUTRAL' && <ShieldAlert className="icon-tiny" />}
              <span>{data.status}</span>
            </div>
          </div>

          <div className="header-title-block">
            <h2 className="underlying-symbol">{data.symbol}</h2>
            <div className="strategy-subtitle-row">
              <span className="strategy-name">{data.strategy}</span>
              <span className="trade-id-pill">{data.tradeId}</span>
            </div>
          </div>
        </div>

        {/* ===================================================================
            2. SUMMARY METRICS ROW (Current Price / Max Target / Max Loss)
           =================================================================== */}
        <div className="card-summary-row">
          <div className="summary-metric-col">
            <span className="metric-label">Current Price</span>
            <span className="metric-value current-price">
              {formatINR(data.currentPrice)}
            </span>
          </div>

          <div className="summary-divider" />

          <div className="summary-metric-col">
            <span className="metric-label">Max Target</span>
            <span className="metric-value max-target">
              {formatINR(data.maxTarget)}
            </span>
          </div>

          <div className="summary-divider" />

          <div className="summary-metric-col">
            <span className="metric-label">Max Loss</span>
            <span className="metric-value max-loss">
              {formatINR(data.maxLoss)}
            </span>
          </div>
        </div>

        {/* ===================================================================
            3. STATUS / TRIGGER MESSAGE BANNER
           =================================================================== */}
        <div className="status-message-banner">
          <Info className="icon-small text-muted" />
          <p className="status-text">{data.statusMessage}</p>
        </div>

        {/* ===================================================================
            4. CAPITAL REQUIRED LINE
           =================================================================== */}
        <div className="capital-required-row">
          <div className="capital-label-group">
            <Wallet className="icon-small text-accent" />
            <span className="capital-title">Capital Required</span>
          </div>
          <span className="capital-amount">{formatINR(data.capitalRequired)}</span>
        </div>

        {/* ===================================================================
            5. STRIKE VISUALIZATION
           =================================================================== */}
        <div className="strike-visualization-section">
          <StrikeVisualizer
            positions={data.positions}
            currentPrice={data.currentPrice}
          />
        </div>

        {/* ===================================================================
            6. POSITIONS LIST / TABLE
           =================================================================== */}
        <div className="positions-list-section">
          <div className="positions-list-header">
            <span>Legs & Contracts</span>
            <span className="legs-count">{data.positions.length} Active</span>
          </div>

          <div className="positions-table">
            {data.positions.map((pos, idx) => (
              <div key={`${pos.strike}-${pos.side}-${idx}`} className="position-row">
                <div className="pos-left-cell">
                  <span
                    className={`side-tag ${
                      pos.side === 'BUY' ? 'tag-buy' : 'tag-sell'
                    }`}
                  >
                    {pos.side}
                  </span>
                  <div className="pos-desc-col">
                    <span className="pos-instrument-title">
                      {pos.strike.toLocaleString('en-IN')}&nbsp;{pos.optionType}&nbsp;
                      <span className="pos-expiry">{pos.expiry}</span>
                    </span>
                    <span className="pos-instrument-type">{pos.instrument}</span>
                  </div>
                </div>

                <div className="pos-right-cell">
                  <span className="pos-qty">{pos.quantity} Qty</span>
                  <span className="pos-price">{formatINR(pos.price)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ===================================================================
            7. TRADE UPDATES BUTTON (Bottom Action)
           =================================================================== */}
        <div className="card-footer-action">
          <button
            type="button"
            className="btn-trade-updates"
            onClick={() => setShowUpdatesModal(true)}
          >
            <History className="icon-small" />
            <span>Trade Updates</span>
          </button>
        </div>
      </div>

      {/* ===================================================================
          INFORMATIONAL "TRADE UPDATES" MODAL (Read-Only Audit Trail)
         =================================================================== */}
      {showUpdatesModal && (
        <div className="trade-updates-backdrop" onClick={() => setShowUpdatesModal(false)}>
          <div
            className="trade-updates-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="modal-header">
              <div className="modal-title-group">
                <History className="icon-small text-accent" />
                <h3>Trade Updates & Audit Trail</h3>
              </div>
              <button
                type="button"
                className="btn-close-modal"
                onClick={() => setShowUpdatesModal(false)}
              >
                <X className="icon-small" />
              </button>
            </div>

            <div className="modal-body">
              <div className="update-item">
                <div className="update-icon-dot success" />
                <div className="update-details">
                  <div className="update-time">{data.timestamp}</div>
                  <div className="update-msg">
                    <strong>Strategy Initialized</strong>: {data.strategy} ({data.symbol}) with {data.positions.length} execution legs.
                  </div>
                </div>
              </div>

              <div className="update-item">
                <div className="update-icon-dot info" />
                <div className="update-details">
                  <div className="update-time">Active Feed</div>
                  <div className="update-msg">
                    Target threshold at {formatINR(data.maxTarget)} | Stop buffer evaluated against max loss of {formatINR(data.maxLoss)}.
                  </div>
                </div>
              </div>

              {data.notes && (
                <div className="update-item">
                  <div className="update-icon-dot neutral" />
                  <div className="update-details">
                    <div className="update-time">Strategy Notes</div>
                    <div className="update-msg">{data.notes}</div>
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn-modal-dismiss"
                onClick={() => setShowUpdatesModal(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
