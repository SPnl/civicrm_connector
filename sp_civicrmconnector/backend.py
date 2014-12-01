# -*- coding: utf-8 -*-
import openerp.addons.connector.backend as backend


civicrm = backend.Backend('civicrm')
""" Generic civicrm Backend """

civicrm7 = backend.Backend(parent=civicrm, version='7.0')
""" civicrm Backend for OpenERP 7 """
