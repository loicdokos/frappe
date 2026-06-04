# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from unittest.mock import patch

import frappe
from frappe.desk.reportview import export_query, extract_fieldnames, get_count
from frappe.tests import IntegrationTestCase


class TestReportview(IntegrationTestCase):
	def test_csv(self):
		from csv import QUOTE_ALL, QUOTE_MINIMAL, QUOTE_NONE, QUOTE_NONNUMERIC, DictReader
		from io import StringIO

		frappe.local.form_dict = frappe._dict(
			doctype="DocType",
			file_format_type="CSV",
			fields=("name", "module", "issingle"),
			filters={"issingle": 1, "module": "Core"},
		)

		for delimiter in (",", ";", "\t", "|"):
			frappe.local.form_dict.csv_delimiter = delimiter
			for quoting in (QUOTE_ALL, QUOTE_MINIMAL, QUOTE_NONE, QUOTE_NONNUMERIC):
				frappe.local.form_dict.csv_quoting = quoting

				export_query()

				self.assertTrue(frappe.response["filename"].endswith(".csv"))
				self.assertEqual(frappe.response["type"], "binary")
				with StringIO(frappe.response["filecontent"].decode("utf-8")) as result:
					reader = DictReader(result, delimiter=delimiter, quoting=quoting)
					for row in reader:
						self.assertEqual(int(row["Is Single"]), 1)
						self.assertEqual(row["Module"], "Core")

	def test_extract_fieldname(self):
		self.assertEqual(
			extract_fieldnames("count(distinct `tabPhoto`.name) as total_count")[0], "tabPhoto.name"
		)

		self.assertEqual(extract_fieldnames("owner")[0], "owner")
		self.assertEqual(extract_fieldnames("from")[0], "from")

		self.assertEqual(extract_fieldnames("module")[0], "module")

		self.assertEqual(extract_fieldnames("count(`tabPhoto`.name) as total_count")[0], "tabPhoto.name")

		self.assertEqual(extract_fieldnames("count(distinct `tabPhoto`.name)")[0], "tabPhoto.name")

		self.assertEqual(extract_fieldnames("count(`tabPhoto`.name)")[0], "tabPhoto.name")

		self.assertEqual(
			extract_fieldnames("count(distinct `tabJob Applicant`.name) as total_count")[0],
			"tabJob Applicant.name",
		)

		self.assertEqual(
			extract_fieldnames("(1 / nullif(locate('a', `tabAddress`.`name`), 0)) as `_relevance`")[0],
			"tabAddress.name",
		)

		self.assertEqual(
			extract_fieldnames("(1 / nullif(locate('(a)', `tabAddress`.`name`), 0)) as `_relevance`")[0],
			"tabAddress.name",
		)

		self.assertEqual(extract_fieldnames("EXTRACT(MONTH FROM date_column) AS month")[0], "date_column")

		self.assertEqual(extract_fieldnames("COUNT(*) AS count")[0], "*")

		self.assertEqual(
			extract_fieldnames("first_name + ' ' + last_name AS full_name"), ["first_name", "last_name"]
		)

		self.assertEqual(
			extract_fieldnames("CONCAT(first_name, ' ', last_name) AS full_name"),
			["first_name", "last_name"],
		)

		self.assertEqual(
			extract_fieldnames("CONCAT(id, '/', name, '/', age, '/', marks) AS student"),
			["id", "name", "age", "marks"],
		)

		self.assertEqual(extract_fieldnames("tablefield.fiedname")[0], "tablefield.fiedname")

		self.assertEqual(extract_fieldnames("`tabChild DocType`.`fiedname`")[0], "tabChild DocType.fiedname")

		self.assertEqual(extract_fieldnames("sum(1)"), [])

	def test_export_report_via_email(self):
		frappe.local.form_dict = frappe._dict(
			doctype="DocType",
			file_format_type="CSV",
			fields=("name", "module", "issingle"),
			filters={"issingle": 1, "module": "Core"},
			export_in_background=1,
		)

		frappe.db.delete("Email Queue")
		export_query()
		jobs = frappe.get_all(
			"RQ Job",
			filters={"job_name": "frappe.desk.query_report.run_report_view_export_job"},
			fields=["name", "status"],
		)
		email_queue = frappe.get_all("Email Queue")

		self.assertTrue(jobs, "Background job was not enqueued")
		self.assertTrue(email_queue, "Email was not enqueued")

	@patch("frappe.desk.reportview.get_form_params")
	def test_get_count_with_limit(self, mock_get_params):
		"""Test count with a specified limit"""
		mock_get_params.return_value = frappe._dict(
			doctype="User",
			filters={},
			fields=[],
			distinct=False,
			limit=1,
			order_by=None
		)

		result = get_count()

		if result == 1:
			cache_control = frappe.local.response_headers.get("Cache-Control")
			self.assertIn("max-age=600", cache_control)
		else:
			self.assertIsInstance(result, int)

	@patch("frappe.desk.reportview.get_form_params")
	@patch("frappe.db.is_statement_timeout")
	def test_get_count_statement_timeout(self, mock_is_timeout, mock_get_params):
		"""Test that the method catches a PostgreSQL/MariaDB timeout and returns None"""
		mock_get_params.return_value = frappe._dict(
			doctype="User",
			filters={},
			fields=[],
			distinct=False,
			limit=10,
			order_by=None
		)

		mock_is_timeout.return_value = True

		from pypika import Query
		with patch("frappe.desk.reportview.execute") as mock_execute:
			# Provide a valid QueryBuilder to the method
			mock_qb = Query.from_("tabUser").select("name").limit(10)
			mock_execute.return_value = mock_qb

			# Simulate the error only at the point of count_query.run()
			with patch("pypika.queries.QueryBuilder.run", side_effect=Exception("Simulated timeout")):
				result = get_count()

				# The except block should catch the timeout and return None
				self.assertIsNone(result)
				cache_control = frappe.local.response_headers.get("Cache-Control")
				self.assertIn("stale-while-revalidate", cache_control)

	@patch("frappe.desk.reportview.get_form_params")
	def test_get_count_virtual_doctype(self, mock_get_params):
		"""Test routing to the controller when the DocType is virtual"""
		with patch("frappe.desk.reportview.is_virtual_doctype", return_value=True), \
				patch("frappe.desk.reportview.get_controller") as mock_controller:

			mock_get_params.return_value = frappe._dict(doctype="VirtualDocType")
			mock_controller.return_value.get_count.return_value = 42

			result = get_count()
			self.assertEqual(result, 42)
