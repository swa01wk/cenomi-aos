import unittest

from aos.kernel.supplier_list_rows import supplier_list_has_real_rows, supplier_row_is_real


class SupplierListRowsTests(unittest.TestCase):
    def test_placeholder_not_real(self) -> None:
        row = {
            "rank": 1,
            "supplier": "No approved suppliers found for this category",
            "supplier_id": "N/A",
            "score": 0,
        }
        self.assertFalse(supplier_row_is_real(row))
        self.assertFalse(supplier_list_has_real_rows({"rows": [row]}))

    def test_real_supplier(self) -> None:
        row = {"rank": 1, "supplier": "Acme", "supplier_id": "SUP-11632", "score": 90}
        self.assertTrue(supplier_row_is_real(row))
        self.assertTrue(supplier_list_has_real_rows({"rows": [row]}))


if __name__ == "__main__":
    unittest.main()
