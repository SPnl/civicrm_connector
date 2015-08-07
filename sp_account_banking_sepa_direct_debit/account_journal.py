from openerp.osv import orm, fields
from openerp.tools.translate import _


class accountJournal(orm.Model):
    _inherit = 'account.journal'

    _columns = {
        'view_direct_debit': fields.boolean('View in direct debit generation', help="View this journal in the filter"
                                                                                    "for direct debit generation")
    }