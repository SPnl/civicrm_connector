# -*- coding: utf-8 -*-

from openerp.osv import fields, orm

import pprint


class product(orm.Model):
    _inherit = 'account.payment.term'
    _columns = {
        'instrument_id': fields.integer('Payment Instrument on Civicrm'),
    }

