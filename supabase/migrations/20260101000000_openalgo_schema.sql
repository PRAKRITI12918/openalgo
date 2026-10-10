-- OpenAlgo Supabase Database Initial Schema
-- Auto-generated for PostgreSQL / Supabase

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==========================================================================
-- 1. TABLES CREATION
-- ==========================================================================

-- Table: active_sessions
CREATE TABLE active_sessions (
	id SERIAL NOT NULL, 
	username VARCHAR(255) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	device_info VARCHAR(500), 
	ip_address VARCHAR(45), 
	broker VARCHAR(20), 
	login_time TIMESTAMP WITH TIME ZONE, 
	last_seen TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (session_id)
);

-- Table: analyzer_logs
CREATE TABLE analyzer_logs (
	id SERIAL NOT NULL, 
	api_type VARCHAR(50) NOT NULL, 
	request_data TEXT NOT NULL, 
	response_data TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: api_keys
CREATE TABLE api_keys (
	id SERIAL NOT NULL, 
	user_id VARCHAR NOT NULL, 
	api_key_hash TEXT NOT NULL, 
	api_key_encrypted TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	order_mode VARCHAR(20), 
	PRIMARY KEY (id), 
	UNIQUE (user_id)
);

-- Table: auth
CREATE TABLE auth (
	id SERIAL NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	auth TEXT NOT NULL, 
	feed_token TEXT, 
	broker VARCHAR(20) NOT NULL, 
	user_id VARCHAR(255), 
	is_revoked BOOLEAN, 
	secret_api_key TEXT, 
	primary_ip VARCHAR(45), 
	secondary_ip VARCHAR(45), 
	ip_updated_at TIMESTAMP WITHOUT TIME ZONE, 
	aux_param1 TEXT, 
	aux_param2 TEXT, 
	aux_param3 TEXT, 
	aux_param4 TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- Table: bot_config
CREATE TABLE bot_config (
	id INTEGER NOT NULL, 
	token TEXT, 
	is_active BOOLEAN, 
	bot_username VARCHAR(255), 
	max_message_length INTEGER, 
	rate_limit_per_minute INTEGER, 
	broadcast_enabled BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: chart_preferences
CREATE TABLE chart_preferences (
	user_id VARCHAR(80) NOT NULL, 
	key VARCHAR(50) NOT NULL, 
	value TEXT, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (user_id, key)
);

-- Table: chartink_strategies
CREATE TABLE chartink_strategies (
	id SERIAL NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	webhook_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	is_active BOOLEAN, 
	is_intraday BOOLEAN, 
	start_time VARCHAR(5), 
	end_time VARCHAR(5), 
	squareoff_time VARCHAR(5), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (webhook_id)
);

-- Table: chartink_symbol_mappings
CREATE TABLE chartink_symbol_mappings (
	id SERIAL NOT NULL, 
	strategy_id INTEGER NOT NULL, 
	chartink_symbol VARCHAR(50) NOT NULL, 
	exchange VARCHAR(10) NOT NULL, 
	quantity INTEGER NOT NULL, 
	product_type VARCHAR(10) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: command_logs
CREATE TABLE command_logs (
	id SERIAL NOT NULL, 
	telegram_id INTEGER NOT NULL, 
	command VARCHAR(100) NOT NULL, 
	chat_id INTEGER, 
	parameters TEXT, 
	executed_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: error_404_tracker
CREATE TABLE error_404_tracker (
	id SERIAL NOT NULL, 
	ip_address VARCHAR(50) NOT NULL, 
	error_count INTEGER, 
	first_error_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	last_error_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	paths_attempted TEXT, 
	PRIMARY KEY (id)
);

-- Table: flow_workflow_executions
CREATE TABLE flow_workflow_executions (
	id SERIAL NOT NULL, 
	workflow_id INTEGER NOT NULL, 
	status VARCHAR(50), 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	logs JSON, 
	error TEXT, 
	PRIMARY KEY (id)
);

-- Table: flow_workflows
CREATE TABLE flow_workflows (
	id SERIAL NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	nodes JSON, 
	edges JSON, 
	is_active BOOLEAN, 
	schedule_job_id VARCHAR(255), 
	webhook_token VARCHAR(64), 
	webhook_secret VARCHAR(64), 
	webhook_enabled BOOLEAN, 
	webhook_auth_type VARCHAR(20), 
	api_key VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (webhook_token)
);

-- Table: health_alerts
CREATE TABLE health_alerts (
	id SERIAL NOT NULL, 
	timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	alert_type VARCHAR(50), 
	severity VARCHAR(20), 
	metric_name VARCHAR(50), 
	metric_value FLOAT, 
	threshold_value FLOAT, 
	message VARCHAR(500), 
	acknowledged BOOLEAN, 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	resolved BOOLEAN, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: health_metrics
CREATE TABLE health_metrics (
	id SERIAL NOT NULL, 
	timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	fd_count INTEGER, 
	fd_limit INTEGER, 
	fd_usage_percent FLOAT, 
	fd_available INTEGER, 
	fd_status VARCHAR(20), 
	memory_rss_mb FLOAT, 
	memory_vms_mb FLOAT, 
	memory_percent FLOAT, 
	memory_available_mb FLOAT, 
	memory_swap_mb FLOAT, 
	memory_status VARCHAR(20), 
	db_connections_total INTEGER, 
	db_connections JSON, 
	db_status VARCHAR(20), 
	ws_connections_total INTEGER, 
	ws_connections JSON, 
	ws_total_symbols INTEGER, 
	ws_status VARCHAR(20), 
	thread_count INTEGER, 
	stuck_threads INTEGER, 
	thread_details JSON, 
	thread_status VARCHAR(20), 
	process_details JSON, 
	overall_status VARCHAR(20), 
	PRIMARY KEY (id)
);

-- Table: invalid_api_key_tracker
CREATE TABLE invalid_api_key_tracker (
	id SERIAL NOT NULL, 
	ip_address VARCHAR(50) NOT NULL, 
	attempt_count INTEGER, 
	first_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	last_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	api_keys_tried TEXT, 
	PRIMARY KEY (id)
);

-- Table: ip_bans
CREATE TABLE ip_bans (
	id SERIAL NOT NULL, 
	ip_address VARCHAR(50) NOT NULL, 
	ban_reason VARCHAR(200), 
	ban_count INTEGER, 
	banned_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	expires_at TIMESTAMP WITH TIME ZONE, 
	is_permanent BOOLEAN, 
	created_by VARCHAR(50), 
	PRIMARY KEY (id)
);

-- Table: leverage_config
CREATE TABLE leverage_config (
	id INTEGER NOT NULL, 
	leverage FLOAT NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: login_attempts
CREATE TABLE login_attempts (
	id SERIAL NOT NULL, 
	username VARCHAR(255) NOT NULL, 
	ip_address VARCHAR(45), 
	device_info VARCHAR(500), 
	status VARCHAR(20) NOT NULL, 
	login_type VARCHAR(20), 
	broker VARCHAR(20), 
	failure_reason VARCHAR(255), 
	timestamp TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: market_holiday_exchanges
CREATE TABLE market_holiday_exchanges (
	id SERIAL NOT NULL, 
	holiday_id INTEGER NOT NULL, 
	exchange_code VARCHAR(10) NOT NULL, 
	is_open BOOLEAN NOT NULL, 
	start_time BIGINT, 
	end_time BIGINT, 
	PRIMARY KEY (id)
);

-- Table: market_holidays
CREATE TABLE market_holidays (
	id SERIAL NOT NULL, 
	holiday_date DATE NOT NULL, 
	description VARCHAR(150) NOT NULL, 
	holiday_type VARCHAR(30) NOT NULL, 
	year INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: market_timings
CREATE TABLE market_timings (
	id SERIAL NOT NULL, 
	exchange_code VARCHAR(10) NOT NULL, 
	start_time VARCHAR(5) NOT NULL, 
	end_time VARCHAR(5) NOT NULL, 
	start_offset BIGINT NOT NULL, 
	end_offset BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: master_contract_status
CREATE TABLE master_contract_status (
	broker VARCHAR NOT NULL, 
	status VARCHAR, 
	message VARCHAR, 
	last_updated TIMESTAMP WITHOUT TIME ZONE, 
	total_symbols VARCHAR, 
	is_ready BOOLEAN, 
	last_download_time TIMESTAMP WITHOUT TIME ZONE, 
	download_date DATE, 
	exchange_stats TEXT, 
	download_duration_seconds INTEGER, 
	PRIMARY KEY (broker)
);

-- Table: notification_queue
CREATE TABLE notification_queue (
	id SERIAL NOT NULL, 
	telegram_id INTEGER NOT NULL, 
	message TEXT NOT NULL, 
	priority INTEGER, 
	status VARCHAR(20), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	sent_at TIMESTAMP WITHOUT TIME ZONE, 
	error_message TEXT, 
	PRIMARY KEY (id)
);

-- Table: oauth_clients
CREATE TABLE oauth_clients (
	id SERIAL NOT NULL, 
	client_id VARCHAR(64) NOT NULL, 
	client_name VARCHAR(255) NOT NULL, 
	redirect_uris TEXT NOT NULL, 
	client_secret_hash TEXT, 
	scopes_requested VARCHAR(255), 
	approved BOOLEAN NOT NULL, 
	approved_at TIMESTAMP WITHOUT TIME ZONE, 
	revoked_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	last_used_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: oauth_refresh_tokens
CREATE TABLE oauth_refresh_tokens (
	id SERIAL NOT NULL, 
	client_id VARCHAR(64) NOT NULL, 
	token_hash TEXT NOT NULL, 
	scopes VARCHAR(255) NOT NULL, 
	family_id VARCHAR(64) NOT NULL, 
	parent_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	last_used_at TIMESTAMP WITHOUT TIME ZONE, 
	revoked_at TIMESTAMP WITHOUT TIME ZONE, 
	revoke_reason VARCHAR(64), 
	PRIMARY KEY (id), 
	UNIQUE (token_hash)
);

-- Table: oauth_signing_keys
CREATE TABLE oauth_signing_keys (
	id SERIAL NOT NULL, 
	kid VARCHAR(64) NOT NULL, 
	algorithm VARCHAR(16) NOT NULL, 
	public_jwk TEXT NOT NULL, 
	private_path VARCHAR(512) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	rotated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: order_latency
CREATE TABLE order_latency (
	id SERIAL NOT NULL, 
	timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	order_id VARCHAR(100) NOT NULL, 
	user_id INTEGER, 
	broker VARCHAR(50), 
	symbol VARCHAR(50), 
	order_type VARCHAR(20), 
	rtt_ms FLOAT, 
	validation_latency_ms FLOAT, 
	response_latency_ms FLOAT, 
	overhead_ms FLOAT, 
	total_latency_ms FLOAT NOT NULL, 
	request_body JSON, 
	response_body JSON, 
	status VARCHAR(20), 
	error VARCHAR(500), 
	PRIMARY KEY (id)
);

-- Table: order_logs
CREATE TABLE order_logs (
	id SERIAL NOT NULL, 
	api_type TEXT NOT NULL, 
	request_data TEXT NOT NULL, 
	response_data TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: pending_orders
CREATE TABLE pending_orders (
	id SERIAL NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	api_type VARCHAR(50) NOT NULL, 
	order_data TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	created_at_ist VARCHAR(50), 
	status VARCHAR(20), 
	approved_at TIMESTAMP WITH TIME ZONE, 
	approved_at_ist VARCHAR(50), 
	approved_by VARCHAR(255), 
	rejected_at TIMESTAMP WITH TIME ZONE, 
	rejected_at_ist VARCHAR(50), 
	rejected_by VARCHAR(255), 
	rejected_reason TEXT, 
	broker_order_id VARCHAR(255), 
	broker_status VARCHAR(20), 
	PRIMARY KEY (id)
);

-- Table: qty_freeze
CREATE TABLE qty_freeze (
	id SERIAL NOT NULL, 
	exchange VARCHAR(10) NOT NULL, 
	symbol VARCHAR(50) NOT NULL, 
	freeze_qty INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: sandbox_config
CREATE TABLE sandbox_config (
	id SERIAL NOT NULL, 
	config_key VARCHAR(100) NOT NULL, 
	config_value TEXT NOT NULL, 
	description TEXT, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: sandbox_daily_pnl
CREATE TABLE sandbox_daily_pnl (
	id SERIAL NOT NULL, 
	user_id VARCHAR(50) NOT NULL, 
	date DATE NOT NULL, 
	realized_pnl DECIMAL(15, 2), 
	positions_unrealized_pnl DECIMAL(15, 2), 
	holdings_unrealized_pnl DECIMAL(15, 2), 
	total_mtm DECIMAL(15, 2), 
	available_balance DECIMAL(15, 2), 
	used_margin DECIMAL(15, 2), 
	portfolio_value DECIMAL(15, 2), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_user_daily_pnl UNIQUE (user_id, date)
);

-- Table: sandbox_funds
CREATE TABLE sandbox_funds (
	id SERIAL NOT NULL, 
	user_id VARCHAR(50) NOT NULL, 
	total_capital DECIMAL(15, 2), 
	available_balance DECIMAL(15, 2), 
	used_margin DECIMAL(15, 2), 
	realized_pnl DECIMAL(15, 2), 
	today_realized_pnl DECIMAL(15, 2), 
	unrealized_pnl DECIMAL(15, 2), 
	total_pnl DECIMAL(15, 2), 
	last_reset_date TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	reset_count INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: sandbox_gtt
CREATE TABLE sandbox_gtt (
	id SERIAL NOT NULL, 
	gtt_id VARCHAR(50) NOT NULL, 
	user_id VARCHAR(50) NOT NULL, 
	strategy VARCHAR(100), 
	trigger_type VARCHAR(10) NOT NULL, 
	symbol VARCHAR(50) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	last_price DECIMAL(10, 2) NOT NULL, 
	gtt_status VARCHAR(20) NOT NULL, 
	margin_blocked DECIMAL(15, 2) NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT check_gtt_trigger_type CHECK (trigger_type IN ('single', 'two-leg')), 
	CONSTRAINT check_gtt_status CHECK (gtt_status IN ('active', 'triggered', 'cancelled', 'expired', 'rejected'))
);

-- Table: sandbox_gtt_legs
CREATE TABLE sandbox_gtt_legs (
	id SERIAL NOT NULL, 
	gtt_id VARCHAR(50) NOT NULL, 
	leg_number INTEGER NOT NULL, 
	trigger_price DECIMAL(10, 2) NOT NULL, 
	trigger_direction VARCHAR(5) NOT NULL, 
	action VARCHAR(10) NOT NULL, 
	quantity INTEGER NOT NULL, 
	price DECIMAL(10, 2) NOT NULL, 
	pricetype VARCHAR(10) NOT NULL, 
	product VARCHAR(10) NOT NULL, 
	leg_status VARCHAR(20) NOT NULL, 
	triggered_order_id VARCHAR(50), 
	leg_margin DECIMAL(15, 2) NOT NULL, 
	claimed_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT check_gtt_trigger_direction CHECK (trigger_direction IN ('below', 'above')), 
	CONSTRAINT check_gtt_leg_status CHECK (leg_status IN ('pending', 'triggering', 'triggered', 'cancelled')), 
	CONSTRAINT check_gtt_leg_action CHECK (action IN ('BUY', 'SELL')), 
	CONSTRAINT check_gtt_leg_product CHECK (product IN ('CNC', 'NRML', 'MIS'))
);

-- Table: sandbox_holdings
CREATE TABLE sandbox_holdings (
	id SERIAL NOT NULL, 
	user_id VARCHAR(50) NOT NULL, 
	symbol VARCHAR(50) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	quantity INTEGER NOT NULL, 
	average_price DECIMAL(10, 2) NOT NULL, 
	ltp DECIMAL(10, 2), 
	pnl DECIMAL(10, 2), 
	pnl_percent DECIMAL(10, 4), 
	settlement_date DATE NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_holding UNIQUE (user_id, symbol, exchange)
);

-- Table: sandbox_orders
CREATE TABLE sandbox_orders (
	id SERIAL NOT NULL, 
	orderid VARCHAR(50) NOT NULL, 
	user_id VARCHAR(50) NOT NULL, 
	strategy VARCHAR(100), 
	symbol VARCHAR(50) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	action VARCHAR(10) NOT NULL, 
	quantity INTEGER NOT NULL, 
	price DECIMAL(10, 2), 
	trigger_price DECIMAL(10, 2), 
	price_type VARCHAR(20) NOT NULL, 
	product VARCHAR(20) NOT NULL, 
	order_status VARCHAR(20) NOT NULL, 
	average_price DECIMAL(10, 2), 
	filled_quantity INTEGER, 
	pending_quantity INTEGER NOT NULL, 
	rejection_reason TEXT, 
	margin_blocked DECIMAL(10, 2), 
	gtt_leg_id INTEGER, 
	order_timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	update_timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT check_order_status CHECK (order_status IN ('open', 'trigger pending', 'complete', 'cancelled', 'rejected')), 
	CONSTRAINT check_action CHECK (action IN ('BUY', 'SELL')), 
	CONSTRAINT check_price_type CHECK (price_type IN ('MARKET', 'LIMIT', 'SL', 'SL-M')), 
	CONSTRAINT check_product CHECK (product IN ('CNC', 'NRML', 'MIS'))
);

-- Table: sandbox_positions
CREATE TABLE sandbox_positions (
	id SERIAL NOT NULL, 
	user_id VARCHAR(50) NOT NULL, 
	symbol VARCHAR(50) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	product VARCHAR(20) NOT NULL, 
	quantity INTEGER NOT NULL, 
	average_price DECIMAL(10, 2) NOT NULL, 
	ltp DECIMAL(10, 2), 
	pnl DECIMAL(10, 2), 
	pnl_percent DECIMAL(10, 4), 
	accumulated_realized_pnl DECIMAL(10, 2), 
	today_realized_pnl DECIMAL(10, 2), 
	margin_blocked DECIMAL(15, 2), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_position UNIQUE (user_id, symbol, exchange, product)
);

-- Table: sandbox_trades
CREATE TABLE sandbox_trades (
	id SERIAL NOT NULL, 
	tradeid VARCHAR(50) NOT NULL, 
	orderid VARCHAR(50) NOT NULL, 
	user_id VARCHAR(50) NOT NULL, 
	symbol VARCHAR(50) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	action VARCHAR(10) NOT NULL, 
	quantity INTEGER NOT NULL, 
	price DECIMAL(10, 2) NOT NULL, 
	product VARCHAR(20) NOT NULL, 
	strategy VARCHAR(100), 
	trade_timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: scalping_sl_state
CREATE TABLE scalping_sl_state (
	id SERIAL NOT NULL, 
	symbol VARCHAR(60) NOT NULL, 
	exchange VARCHAR(10) NOT NULL, 
	product VARCHAR(10) NOT NULL, 
	side VARCHAR(4) NOT NULL, 
	mode VARCHAR(10) NOT NULL, 
	entry_price FLOAT NOT NULL, 
	quantity INTEGER NOT NULL, 
	initial_sl FLOAT, 
	trailing_enabled BOOLEAN NOT NULL, 
	trailing_step FLOAT, 
	highest_price FLOAT, 
	lowest_price FLOAT, 
	current_sl FLOAT, 
	target FLOAT, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_scalping_sl_leg UNIQUE (symbol, exchange, product, mode)
);

-- Table: scalping_tracked_symbol
CREATE TABLE scalping_tracked_symbol (
	id SERIAL NOT NULL, 
	symbol VARCHAR(60) NOT NULL, 
	exchange VARCHAR(10) NOT NULL, 
	product VARCHAR(10) NOT NULL, 
	mode VARCHAR(10) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_scalping_tracked UNIQUE (symbol, exchange, product, mode)
);

-- Table: settings
CREATE TABLE settings (
	id SERIAL NOT NULL, 
	analyze_mode BOOLEAN, 
	smtp_server VARCHAR(255), 
	smtp_port INTEGER, 
	smtp_username VARCHAR(255), 
	smtp_password_encrypted TEXT, 
	smtp_use_tls BOOLEAN, 
	smtp_from_email VARCHAR(255), 
	smtp_helo_hostname VARCHAR(255), 
	security_auto_ban_enabled BOOLEAN, 
	security_404_threshold INTEGER, 
	security_404_ban_duration INTEGER, 
	security_api_threshold INTEGER, 
	security_api_ban_duration INTEGER, 
	security_repeat_offender_limit INTEGER, 
	PRIMARY KEY (id)
);

-- Table: strategies
CREATE TABLE strategies (
	id SERIAL NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	webhook_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	platform VARCHAR(50) NOT NULL, 
	is_active BOOLEAN, 
	is_intraday BOOLEAN, 
	trading_mode VARCHAR(10) NOT NULL, 
	start_time VARCHAR(5), 
	end_time VARCHAR(5), 
	squareoff_time VARCHAR(5), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (webhook_id)
);

-- Table: strategy_order_tags
CREATE TABLE strategy_order_tags (
	id SERIAL NOT NULL, 
	orderid VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	strategy VARCHAR(120) NOT NULL, 
	symbol VARCHAR(64) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	product VARCHAR(20) NOT NULL, 
	applied_quantity FLOAT NOT NULL, 
	applied_notional FLOAT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: strategy_pending_fills
CREATE TABLE strategy_pending_fills (
	id SERIAL NOT NULL, 
	orderid VARCHAR(64) NOT NULL, 
	filled_quantity FLOAT NOT NULL, 
	average_price FLOAT NOT NULL, 
	action VARCHAR(10) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: strategy_portfolio
CREATE TABLE strategy_portfolio (
	id SERIAL NOT NULL, 
	watchlist VARCHAR(20) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	underlying VARCHAR(40) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	expiry VARCHAR(20), 
	legs_json TEXT NOT NULL, 
	notes TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: strategy_positions
CREATE TABLE strategy_positions (
	id SERIAL NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	strategy VARCHAR(120) NOT NULL, 
	symbol VARCHAR(64) NOT NULL, 
	exchange VARCHAR(20) NOT NULL, 
	product VARCHAR(20) NOT NULL, 
	quantity FLOAT NOT NULL, 
	average_price FLOAT NOT NULL, 
	realized_pnl FLOAT NOT NULL, 
	today_realized_pnl FLOAT NOT NULL, 
	trade_date VARCHAR(10), 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_strategy_leg UNIQUE (user_id, strategy, symbol, exchange, product)
);

-- Table: strategy_symbol_mappings
CREATE TABLE strategy_symbol_mappings (
	id SERIAL NOT NULL, 
	strategy_id INTEGER NOT NULL, 
	symbol VARCHAR(50) NOT NULL, 
	exchange VARCHAR(10) NOT NULL, 
	quantity INTEGER NOT NULL, 
	product_type VARCHAR(10) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: symtoken
CREATE TABLE symtoken (
	id INTEGER NOT NULL, 
	symbol VARCHAR NOT NULL, 
	brsymbol VARCHAR NOT NULL, 
	name VARCHAR, 
	exchange VARCHAR, 
	brexchange VARCHAR, 
	token VARCHAR, 
	expiry VARCHAR, 
	strike FLOAT, 
	lotsize INTEGER, 
	instrumenttype VARCHAR, 
	tick_size FLOAT, 
	contract_value FLOAT, 
	PRIMARY KEY (id)
);

-- Table: telegram_users
CREATE TABLE telegram_users (
	id SERIAL NOT NULL, 
	telegram_id INTEGER NOT NULL, 
	openalgo_username VARCHAR(255) NOT NULL, 
	encrypted_api_key TEXT, 
	host_url VARCHAR(500), 
	first_name VARCHAR(255), 
	last_name VARCHAR(255), 
	telegram_username VARCHAR(255), 
	broker VARCHAR(50), 
	is_active BOOLEAN, 
	notifications_enabled BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	last_command_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: traffic_logs
CREATE TABLE traffic_logs (
	id SERIAL NOT NULL, 
	timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	client_ip VARCHAR(50) NOT NULL, 
	method VARCHAR(10) NOT NULL, 
	path VARCHAR(500) NOT NULL, 
	status_code INTEGER NOT NULL, 
	duration_ms FLOAT NOT NULL, 
	host VARCHAR(500), 
	error VARCHAR(500), 
	user_id INTEGER, 
	PRIMARY KEY (id)
);

-- Table: user_preferences
CREATE TABLE user_preferences (
	telegram_id INTEGER NOT NULL, 
	order_notifications BOOLEAN, 
	trade_notifications BOOLEAN, 
	pnl_notifications BOOLEAN, 
	daily_summary BOOLEAN, 
	summary_time VARCHAR(10), 
	language VARCHAR(10), 
	timezone VARCHAR(50), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (telegram_id)
);

-- Table: users
CREATE TABLE users (
	id SERIAL NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	totp_secret VARCHAR(255) NOT NULL, 
	is_admin BOOLEAN, 
	totp_enabled BOOLEAN NOT NULL, 
	totp_required_for_login BOOLEAN NOT NULL, 
	totp_required_for_mcp BOOLEAN NOT NULL, 
	totp_required_for_password_reset BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username), 
	UNIQUE (email)
);

-- Table: whatsapp_command_logs
CREATE TABLE whatsapp_command_logs (
	id SERIAL NOT NULL, 
	whatsapp_jid VARCHAR(120) NOT NULL, 
	command VARCHAR(100) NOT NULL, 
	parameters TEXT, 
	executed_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: whatsapp_config
CREATE TABLE whatsapp_config (
	id INTEGER NOT NULL, 
	session_blob BYTEA, 
	own_jid VARCHAR(120), 
	own_phone VARCHAR(32), 
	bot_username VARCHAR(255), 
	owner_user_id INTEGER, 
	owner_username VARCHAR(255), 
	is_paired BOOLEAN, 
	is_active BOOLEAN, 
	paired_at TIMESTAMP WITHOUT TIME ZONE, 
	max_message_length INTEGER, 
	rate_limit_per_minute INTEGER, 
	broadcast_enabled BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- Table: whatsapp_notification_queue
CREATE TABLE whatsapp_notification_queue (
	id SERIAL NOT NULL, 
	whatsapp_jid VARCHAR(120) NOT NULL, 
	message TEXT NOT NULL, 
	media_path TEXT, 
	media_kind VARCHAR(20), 
	priority INTEGER, 
	status VARCHAR(20), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	sent_at TIMESTAMP WITHOUT TIME ZONE, 
	error_message TEXT, 
	PRIMARY KEY (id)
);

-- Table: whatsapp_user_preferences
CREATE TABLE whatsapp_user_preferences (
	whatsapp_jid VARCHAR(120) NOT NULL, 
	order_notifications BOOLEAN, 
	trade_notifications BOOLEAN, 
	pnl_notifications BOOLEAN, 
	daily_summary BOOLEAN, 
	summary_time VARCHAR(10), 
	language VARCHAR(10), 
	timezone VARCHAR(50), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (whatsapp_jid)
);

-- Table: whatsapp_users
CREATE TABLE whatsapp_users (
	id SERIAL NOT NULL, 
	whatsapp_jid VARCHAR(120) NOT NULL, 
	phone_number VARCHAR(32) NOT NULL, 
	openalgo_username VARCHAR(255) NOT NULL, 
	encrypted_api_key TEXT, 
	host_url VARCHAR(500), 
	display_name VARCHAR(255), 
	broker VARCHAR(50), 
	is_active BOOLEAN, 
	notifications_enabled BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	last_command_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

-- ==========================================================================
-- 2. INDEXES
-- ==========================================================================

CREATE INDEX idx_active_sessions_username ON active_sessions (username);
CREATE INDEX ix_active_sessions_username ON active_sessions (username);

CREATE INDEX idx_analyzer_api_type ON analyzer_logs (api_type);
CREATE INDEX idx_analyzer_created_at ON analyzer_logs (created_at);
CREATE INDEX idx_analyzer_type_time ON analyzer_logs (api_type, created_at);

CREATE INDEX idx_api_keys_order_mode ON api_keys (order_mode);
CREATE INDEX idx_api_keys_created_at ON api_keys (created_at);

CREATE INDEX idx_auth_user_id ON auth (user_id);
CREATE INDEX idx_auth_is_revoked ON auth (is_revoked);
CREATE INDEX idx_auth_broker ON auth (broker);





CREATE INDEX ix_command_logs_telegram_id ON command_logs (telegram_id);

CREATE INDEX idx_404_first_error_at ON error_404_tracker (first_error_at);
CREATE INDEX ix_error_404_tracker_ip_address ON error_404_tracker (ip_address);
CREATE INDEX idx_404_error_count ON error_404_tracker (error_count);

CREATE INDEX ix_flow_workflow_executions_id ON flow_workflow_executions (id);

CREATE INDEX ix_flow_workflows_id ON flow_workflows (id);



CREATE INDEX idx_api_tracker_attempt_count ON invalid_api_key_tracker (attempt_count);
CREATE INDEX ix_invalid_api_key_tracker_ip_address ON invalid_api_key_tracker (ip_address);
CREATE INDEX idx_api_tracker_first_attempt_at ON invalid_api_key_tracker (first_attempt_at);

CREATE UNIQUE INDEX ix_ip_bans_ip_address ON ip_bans (ip_address);


CREATE INDEX idx_login_attempts_status ON login_attempts (status);
CREATE INDEX idx_login_attempts_username ON login_attempts (username);
CREATE INDEX idx_login_attempts_timestamp ON login_attempts (timestamp);

CREATE INDEX idx_holiday_exchange ON market_holiday_exchanges (holiday_id, exchange_code);
CREATE INDEX ix_market_holiday_exchanges_holiday_id ON market_holiday_exchanges (holiday_id);
CREATE INDEX ix_market_holiday_exchanges_exchange_code ON market_holiday_exchanges (exchange_code);

CREATE INDEX idx_holiday_date_year ON market_holidays (holiday_date, year);
CREATE INDEX ix_market_holidays_year ON market_holidays (year);
CREATE INDEX ix_market_holidays_holiday_date ON market_holidays (holiday_date);

CREATE UNIQUE INDEX ix_market_timings_exchange_code ON market_timings (exchange_code);


CREATE INDEX ix_notification_queue_status ON notification_queue (status);

CREATE INDEX idx_oauth_client_approved ON oauth_clients (approved, revoked_at);
CREATE UNIQUE INDEX ix_oauth_clients_client_id ON oauth_clients (client_id);

CREATE INDEX ix_oauth_refresh_tokens_revoked_at ON oauth_refresh_tokens (revoked_at);
CREATE INDEX ix_oauth_refresh_tokens_family_id ON oauth_refresh_tokens (family_id);
CREATE INDEX ix_oauth_refresh_tokens_client_id ON oauth_refresh_tokens (client_id);

CREATE UNIQUE INDEX ix_oauth_signing_keys_kid ON oauth_signing_keys (kid);



CREATE INDEX idx_created_at ON pending_orders (created_at);
CREATE INDEX idx_user_status ON pending_orders (user_id, status);

CREATE UNIQUE INDEX idx_exchange_symbol ON qty_freeze (exchange, symbol);
CREATE INDEX ix_qty_freeze_symbol ON qty_freeze (symbol);
CREATE INDEX ix_qty_freeze_exchange ON qty_freeze (exchange);

CREATE UNIQUE INDEX ix_sandbox_config_config_key ON sandbox_config (config_key);

CREATE INDEX ix_sandbox_daily_pnl_date ON sandbox_daily_pnl (date);
CREATE INDEX idx_user_date ON sandbox_daily_pnl (user_id, date);
CREATE INDEX ix_sandbox_daily_pnl_user_id ON sandbox_daily_pnl (user_id);

CREATE UNIQUE INDEX ix_sandbox_funds_user_id ON sandbox_funds (user_id);

CREATE INDEX idx_gtt_symbol_exchange ON sandbox_gtt (symbol, exchange);
CREATE INDEX ix_sandbox_gtt_symbol ON sandbox_gtt (symbol);
CREATE INDEX ix_sandbox_gtt_exchange ON sandbox_gtt (exchange);
CREATE INDEX idx_gtt_user_status ON sandbox_gtt (user_id, gtt_status);
CREATE UNIQUE INDEX ix_sandbox_gtt_gtt_id ON sandbox_gtt (gtt_id);
CREATE INDEX ix_sandbox_gtt_user_id ON sandbox_gtt (user_id);
CREATE INDEX ix_sandbox_gtt_gtt_status ON sandbox_gtt (gtt_status);

CREATE INDEX idx_gtt_leg_status_claimed ON sandbox_gtt_legs (leg_status, claimed_at);
CREATE INDEX ix_sandbox_gtt_legs_gtt_id ON sandbox_gtt_legs (gtt_id);

CREATE INDEX ix_sandbox_holdings_exchange ON sandbox_holdings (exchange);
CREATE INDEX ix_sandbox_holdings_user_id ON sandbox_holdings (user_id);
CREATE INDEX ix_sandbox_holdings_symbol ON sandbox_holdings (symbol);

CREATE UNIQUE INDEX ix_sandbox_orders_gtt_leg_id ON sandbox_orders (gtt_leg_id);
CREATE INDEX idx_sandbox_symbol_exchange ON sandbox_orders (symbol, exchange);
CREATE UNIQUE INDEX ix_sandbox_orders_orderid ON sandbox_orders (orderid);
CREATE INDEX ix_sandbox_orders_order_status ON sandbox_orders (order_status);
CREATE INDEX ix_sandbox_orders_symbol ON sandbox_orders (symbol);
CREATE INDEX ix_sandbox_orders_exchange ON sandbox_orders (exchange);
CREATE INDEX idx_sandbox_user_status ON sandbox_orders (user_id, order_status);
CREATE INDEX ix_sandbox_orders_user_id ON sandbox_orders (user_id);

CREATE INDEX ix_sandbox_positions_exchange ON sandbox_positions (exchange);
CREATE INDEX idx_user_product ON sandbox_positions (user_id, product);
CREATE INDEX ix_sandbox_positions_user_id ON sandbox_positions (user_id);
CREATE INDEX ix_sandbox_positions_symbol ON sandbox_positions (symbol);

CREATE INDEX ix_sandbox_trades_orderid ON sandbox_trades (orderid);
CREATE INDEX ix_sandbox_trades_user_id ON sandbox_trades (user_id);
CREATE INDEX idx_orderid ON sandbox_trades (orderid);
CREATE UNIQUE INDEX ix_sandbox_trades_tradeid ON sandbox_trades (tradeid);
CREATE INDEX ix_sandbox_trades_exchange ON sandbox_trades (exchange);
CREATE INDEX idx_user_symbol ON sandbox_trades (user_id, symbol);
CREATE INDEX ix_sandbox_trades_symbol ON sandbox_trades (symbol);

CREATE INDEX ix_scalping_sl_state_id ON scalping_sl_state (id);

CREATE INDEX ix_scalping_tracked_symbol_id ON scalping_tracked_symbol (id);



CREATE INDEX ix_strategy_order_tags_user_id ON strategy_order_tags (user_id);
CREATE INDEX ix_strategy_order_tags_strategy ON strategy_order_tags (strategy);
CREATE UNIQUE INDEX ix_strategy_order_tags_orderid ON strategy_order_tags (orderid);

CREATE INDEX ix_strategy_pending_fills_orderid ON strategy_pending_fills (orderid);

CREATE INDEX ix_strategy_portfolio_watchlist ON strategy_portfolio (watchlist);

CREATE INDEX ix_strategy_positions_symbol ON strategy_positions (symbol);
CREATE INDEX ix_strategy_positions_user_id ON strategy_positions (user_id);
CREATE INDEX ix_strategy_positions_strategy ON strategy_positions (strategy);


CREATE INDEX ix_symtoken_brsymbol ON symtoken (brsymbol);
CREATE INDEX ix_symtoken_exchange ON symtoken (exchange);
CREATE INDEX idx_symbol_name ON symtoken (symbol, name);
CREATE INDEX idx_brsymbol_exchange ON symtoken (brsymbol, exchange);
CREATE INDEX ix_symtoken_symbol ON symtoken (symbol);
CREATE INDEX ix_symtoken_token ON symtoken (token);
CREATE INDEX idx_symbol_exchange ON symtoken (symbol, exchange);
CREATE INDEX ix_symtoken_brexchange ON symtoken (brexchange);

CREATE UNIQUE INDEX ix_telegram_users_telegram_id ON telegram_users (telegram_id);
CREATE INDEX ix_telegram_users_openalgo_username ON telegram_users (openalgo_username);

CREATE INDEX idx_traffic_ip_timestamp ON traffic_logs (client_ip, timestamp);
CREATE INDEX idx_traffic_status_code ON traffic_logs (status_code);
CREATE INDEX idx_traffic_timestamp ON traffic_logs (timestamp);
CREATE INDEX idx_traffic_user_id ON traffic_logs (user_id);
CREATE INDEX idx_traffic_client_ip ON traffic_logs (client_ip);



CREATE INDEX ix_whatsapp_command_logs_whatsapp_jid ON whatsapp_command_logs (whatsapp_jid);


CREATE INDEX ix_whatsapp_notification_queue_status ON whatsapp_notification_queue (status);


CREATE INDEX ix_whatsapp_users_phone_number ON whatsapp_users (phone_number);
CREATE INDEX ix_whatsapp_users_openalgo_username ON whatsapp_users (openalgo_username);
CREATE UNIQUE INDEX ix_whatsapp_users_whatsapp_jid ON whatsapp_users (whatsapp_jid);

-- ==========================================================================
-- 3. FOREIGN KEY CONSTRAINTS
-- ==========================================================================

ALTER TABLE chartink_symbol_mappings ADD FOREIGN KEY(strategy_id) REFERENCES chartink_strategies (id);
ALTER TABLE command_logs ADD FOREIGN KEY(telegram_id) REFERENCES telegram_users (telegram_id);
ALTER TABLE flow_workflow_executions ADD FOREIGN KEY(workflow_id) REFERENCES flow_workflows (id);
ALTER TABLE notification_queue ADD FOREIGN KEY(telegram_id) REFERENCES telegram_users (telegram_id);
ALTER TABLE oauth_refresh_tokens ADD FOREIGN KEY(parent_id) REFERENCES oauth_refresh_tokens (id);
ALTER TABLE sandbox_gtt_legs ADD FOREIGN KEY(gtt_id) REFERENCES sandbox_gtt (gtt_id) ON DELETE CASCADE;
ALTER TABLE strategy_symbol_mappings ADD FOREIGN KEY(strategy_id) REFERENCES strategies (id);
ALTER TABLE user_preferences ADD FOREIGN KEY(telegram_id) REFERENCES telegram_users (telegram_id);
ALTER TABLE whatsapp_command_logs ADD FOREIGN KEY(whatsapp_jid) REFERENCES whatsapp_users (whatsapp_jid);
ALTER TABLE whatsapp_notification_queue ADD FOREIGN KEY(whatsapp_jid) REFERENCES whatsapp_users (whatsapp_jid);
ALTER TABLE whatsapp_user_preferences ADD FOREIGN KEY(whatsapp_jid) REFERENCES whatsapp_users (whatsapp_jid);
