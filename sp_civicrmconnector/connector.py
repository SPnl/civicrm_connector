from openerp.addons.connector.connector import install_in_connector
from openerp.addons.connector.connector import Environment
from openerp.addons.connector.checkpoint import checkpoint
from openerp.osv import orm, fields

install_in_connector()

def get_environment(session, model_name, backend_id):
    """ Create an environment to work with. """
    backend_record = session.browse('civicrm.backend', backend_id)
    env = Environment(backend_record, session, model_name)
    env.set_lang(code='nl_NL')
    return env


def add_checkpoint(session, model_name, record_id, backend_id):
    return checkpoint.add_checkpoint(session, model_name, record_id,
                                     'civicrm.backend', backend_id)
