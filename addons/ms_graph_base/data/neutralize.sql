-- Auto-run by Odoo during a neutralized database restore (the loader executes
-- every installed module's data/neutralize.sql; see odoo/modules/neutralize.py).
--
-- ms.entra.auth is the single entry point for all Microsoft Entra / Graph
-- access in this codebase (mailbox collection, calendar sync, outbound mail).
-- Clearing every credential makes the token request fail closed, so a
-- neutralized (non-production) copy cannot authenticate to or act against
-- production Microsoft 365. Core neutralize.sql only covers SMTP/fetchmail and
-- is unaware of these custom ir_config_parameter rows.
UPDATE ir_config_parameter
   SET value = ''
 WHERE key IN ('ms_graph.client_secret',
               'ms_graph.certificate',
               'ms_graph.certificate_path',
               'ms_graph.certificate_password');

-- Managed and workload identity need no stored credential: a neutralized copy
-- restored on the same Azure host or in the same AKS pod would still get a
-- production token. Force it back to the secret flow, whose secret was just
-- cleared.
UPDATE ir_config_parameter
   SET value = 'client_secret'
 WHERE key = 'ms_graph.auth_mode';
