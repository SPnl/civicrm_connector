# -*- coding: utf-8 -*-

from openerp.osv import fields, orm
from openerp.addons.connector.event import on_record_write
from openerp.addons.connector.event import on_record_create
from openerp.addons.connector.event import on_record_unlink
# from .unit.export_synchronizer import export_record
from connector import get_environment
from openerp.addons.connector.connector import ConnectorUnit
from openerp.addons.connector.unit.synchronizer import ExportSynchronizer
from backend import civicrm
from openerp.addons.connector.connector import Binder
from datetime import datetime
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp.addons.connector.queue.job import job
from binder import CivicrmBinder

from civicrm import Civicrm
from pythoncivicrm import *
import time
import pprint

class CiviCRMExportSynchronizer(ExportSynchronizer):
    def _makecivitime(self, importTime):
        date_obj = time.strptime(importTime, "%Y-%m-%d")
        civitime = time.strftime("%Y%m%d000000", date_obj )
        return civitime
