# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import json

import frappe
from frappe.model import no_value_fields, table_fields
from frappe.model.utils.user_settings import sync_user_settings, update_user_settings_data
from frappe.utils.password import rename_password_field


def rename_field(doctype, old_fieldname, new_fieldname, validate=True):
	"""This functions assumes that doctype is already synced"""

	meta = frappe.get_meta(doctype, cached=False)
	new_field = meta.get_field(new_fieldname)

	if validate:
		if not new_field:
			print("rename_field: " + (new_fieldname) + " not found in " + doctype)
			return

		if not meta.issingle and not frappe.db.has_column(doctype, old_fieldname):
			print("rename_field: " + (old_fieldname) + " not found in table for: " + doctype)
			# never had the field?
			return

	if new_field.fieldtype in table_fields:
		# change parentfield of table mentioned in options
		target_doctype_name = new_field.options.split("\n", 1)[0]
		TargetDocType = frappe.qb.DocType(target_doctype_name)
		(
			frappe.qb.update(TargetDocType)
			.set(TargetDocType.parentfield, new_fieldname)
			.where(TargetDocType.parentfield == old_fieldname)
		).run()

	elif new_field.fieldtype not in no_value_fields:
		if meta.issingle:
			Singles = frappe.qb.DocType("Singles")
			(
				frappe.qb.update(Singles)
				.set(Singles.field, new_fieldname)
				.where(Singles.doctype == doctype)
				.where(Singles.field == old_fieldname)
			).run()
		else:
			# copy field value
			TargetDocType = frappe.qb.DocType(doctype)
			new_field = getattr(TargetDocType, new_fieldname)
			old_field = getattr(TargetDocType, old_fieldname)
			(
				frappe.qb.update(TargetDocType)
				.set(new_field, old_field)
			).run()

		update_reports(doctype, old_fieldname, new_fieldname)
		update_users_report_view_settings(doctype, old_fieldname, new_fieldname)

		if new_field.fieldtype == "Password":
			rename_password_field(doctype, old_fieldname, new_fieldname)

	# update in property setter
	update_property_setters(doctype, old_fieldname, new_fieldname)

	# update in user settings
	update_user_settings(doctype, old_fieldname, new_fieldname)


def update_reports(doctype, old_fieldname, new_fieldname):
	from frappe.query_builder.functions import IfNull
	def _get_new_sort_by(report_dict, report, key):
		sort_by = report_dict.get(key) or ""
		if sort_by:
			sort_by = sort_by.split(".")
			if len(sort_by) > 1:
				if sort_by[0] == doctype and sort_by[1] == old_fieldname:
					sort_by = doctype + "." + new_fieldname
					report_dict["updated"] = True
			elif report.ref_doctype == doctype and sort_by[0] == old_fieldname:
				sort_by = doctype + "." + new_fieldname
				report_dict["updated"] = True

			if isinstance(sort_by, list):
				sort_by = ".".join(sort_by)

		return sort_by

	Report = frappe.qb.DocType("Report")
	query = (
    frappe.qb.from_(Report)
    .select(Report.name, Report.ref_doctype, Report.json)
    .where(Report.report_type == "Report Builder")
    .where(IfNull(Report.is_standard, "No") == "No")
    .where(Report.json.like(f"%{old_fieldname}%"))
    .where(Report.json.like(f"%{doctype}%"))
	)
	reports = query.run(as_dict=True)
	for r in reports:
		report_dict = json.loads(r.json)

		# update filters
		new_filters = []
		if report_dict.get("filters"):
			for f in report_dict.get("filters"):
				if f and len(f) > 1 and f[0] == doctype and f[1] == old_fieldname:
					new_filters.append([doctype, new_fieldname, f[2], f[3]])
					report_dict["updated"] = True
				else:
					new_filters.append(f)

		# update columns
		new_columns = []
		if report_dict.get("columns"):
			for c in report_dict.get("columns"):
				if c and len(c) > 1 and c[0] == old_fieldname and c[1] == doctype:
					new_columns.append([new_fieldname, doctype])
					report_dict["updated"] = True
				else:
					new_columns.append(c)

		# update sort by
		new_sort_by = _get_new_sort_by(report_dict, r, "sort_by")
		new_sort_by_next = _get_new_sort_by(report_dict, r, "sort_by_next")

		if report_dict.get("updated"):
			new_val = json.dumps(
				{
					"filters": new_filters,
					"columns": new_columns,
					"sort_by": new_sort_by,
					"sort_order": report_dict.get("sort_order"),
					"sort_by_next": new_sort_by_next,
					"sort_order_next": report_dict.get("sort_order_next"),
				}
			)
			Report = frappe.qb.DocType("Report")
			(
				frappe.qb.update(Report)
				.set(Report.json, new_val)
				.where(Report.name == r.name)
			).run()


def update_users_report_view_settings(doctype, ref_fieldname, new_fieldname):
	DefaultValue = frappe.qb.DocType("DefaultValue")
	query = (
    frappe.qb.from_(DefaultValue)
    .select(DefaultValue.defkey, DefaultValue.defvalue)
    .where(DefaultValue.defkey.like("_list_settings:%"))
	)
	user_report_cols = query.run()
	for key, value in user_report_cols:
		new_columns = []
		columns_modified = False
		for field, field_doctype in json.loads(value):
			if field == ref_fieldname and field_doctype == doctype:
				new_columns.append([new_fieldname, field_doctype])
				columns_modified = True
			else:
				new_columns.append([field, field_doctype])

		if columns_modified:
			DefaultValue = frappe.qb.DocType("DefaultValue")
			(
				frappe.qb.update(DefaultValue)
				.set(DefaultValue.defvalue, json.dumps(new_columns))
				.where(DefaultValue.defkey == key)
			).run()


def update_property_setters(doctype, old_fieldname, new_fieldname):
	PropertySetter = frappe.qb.DocType("Property Setter")
	(
        frappe.qb.update(PropertySetter)
        .set(PropertySetter.field_name, new_fieldname)
        .where(PropertySetter.doc_type == doctype)
        .where(PropertySetter.field_name == old_fieldname)
    ).run()

	CustomField = frappe.qb.DocType("Custom Field")
	(
        frappe.qb.update(CustomField)
        .set(CustomField.insert_after, new_fieldname)
        .where(CustomField.insert_after == old_fieldname)
        .where(CustomField.dt == doctype)
    ).run()


def update_user_settings(doctype, old_fieldname, new_fieldname):
	# store the user settings data from the redis to db
	sync_user_settings()

	user_settings = frappe.db.sql(
		""" select user, doctype, data from `__UserSettings`
		where doctype=%s and data like %s""",
		(doctype, f"%{old_fieldname}%"),
		as_dict=1,
	)

	for user_setting in user_settings:
		update_user_settings_data(user_setting, "docfield", old_fieldname, new_fieldname)
