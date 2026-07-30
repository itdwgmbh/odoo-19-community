-- Auto-run by Odoo during a neutralized database restore (the loader executes
-- every installed module's data/neutralize.sql; see odoo/modules/neutralize.py).
--
-- ms.graph.service is the single entry point for all Microsoft Graph access in
-- this codebase (mailbox collection, calendar sync, outbound mail), each via a
-- client-credentials token. Clearing the app secret makes that token request
-- fail closed, so a neutralized (non-production) copy cannot authenticate to or
-- act against production Microsoft 365. Core neutralize.sql only covers
-- SMTP/fetchmail and is unaware of these custom ir_config_parameter rows.
UPDATE ir_config_parameter
   SET value = ''
 WHERE key = 'ms_graph.client_secret';
