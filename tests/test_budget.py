"""Bilan de cycle (budget.py) : données synthétiques, règles de reconnaissance du propriétaire."""
import unittest
from datetime import date

from jarvis.core.budget import CM, TR, report


def tx(bank, day, amount, label=""):
    return {"bank": bank, "date": day, "amount": amount, "label": label}


CYCLE = [
    tx(CM, "2026-08-28", 2500.00, "VIR SEPA EMPLOYEUR SALAIRE"),
    tx(CM, "2026-09-01", -150.00, "VIR LIVRET DE DEVELOPPEMENT DURABLE"),
    tx(CM, "2026-09-05", -600.00, "ECH PRET CAP+IN 001"), tx(CM, "2026-09-05", -130.00, "ECH PRET CAP+IN 002"),
    tx(CM, "2026-09-05", -8.25, "F COTIS EUROCOMPTE JEUNE ACTIF"),
    tx(CM, "2026-09-08", -31.16, "ASSURANCE HABITATION"),
    tx(CM, "2026-09-11", -103.65, "PRLV SEPA CONSEIL INVEST 34"),
    tx(CM, "2026-09-10", -10.00, "PAIEMENTS 1009 VEDENE CEDEX ASF-GARE CARTE"), tx(CM, "2026-09-15", -16.60, "PAIEMENTS 1509 VEDENE CEDEX ASF-GARE CARTE"),
    tx(CM, "2026-09-25", -49.00, "PRLV SEPA DIRECTION GENERALE DES FINANCES"),
    tx(CM, "2026-09-12", 29.00, "VIR INST M. Ami Un"),
    tx(CM, "2026-09-15", 500.00, "VIR DE M ROMAIN CHEVALIER"),
    tx(CM, "2026-09-20", 12.00, "VIR NEWORCH INVOICE"),
    tx(TR, "2026-09-02", -0.42), tx(TR, "2026-09-02", 0.03),
    tx(TR, "2026-09-02", 200.00),
    tx(TR, "2026-09-02", -1.00), tx(TR, "2026-09-02", -16.00),
    tx(TR, "2026-09-14", -24.99), tx(TR, "2026-09-23", -24.99),
    tx(TR, "2026-09-09", -10.00), tx(TR, "2026-09-09", -15.00), tx(TR, "2026-09-09", -67.00), tx(TR, "2026-09-09", -3.37),
    tx(TR, "2026-09-11", -85.01),
    tx(TR, "2026-09-19", -126.99),
    tx(TR, "2026-09-26", -216.00),
    tx(TR, "2026-09-05", -81.45, "TICKETMASTER"),
    tx(TR, "2026-09-04", -3.90),
]


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.r = report(CYCLE, date(2026, 9, 28))

    def test_paie_au_libelle_neworch(self):
        r = report([tx(CM, "2026-09-29", 2362.05, "NEWORCH"), tx(CM, "2026-09-30", 12.0, "VIR NEWORCH INVOICE")], date(2026, 10, 9))
        self.assertEqual(r["pay"]["amount"], 2362.05)

    def test_sans_paie_pas_de_bilan(self):
        self.assertIsNone(report([tx(CM, "2026-09-05", -8.25, "COTIS EUROCOMPTE")], date(2026, 9, 28)))

    def test_paie_et_debut_de_cycle(self):
        self.assertEqual((self.r["start"], self.r["pay"]["amount"]), ("2026-08-28", 2500.0))

    def test_credit_en_une_seule_ligne(self):
        credit = [x for x in self.r["fixed"]["items"] if x["name"] == "Crédit"]
        self.assertEqual(len(credit), 1)
        self.assertEqual(credit[0]["amount"], 730.0)
        self.assertIn("2 prêts", credit[0]["detail"])

    def test_charges_fixes(self):
        names = {x["name"] for x in self.r["fixed"]["items"]}
        self.assertEqual(names, {"Crédit", "Cotisation compte", "Assurance habitation", "Charges de copropriété", "Internet", "Basic Fit"})
        self.assertEqual(self.r["fixed"]["total"], 730 + 8.25 + 31.16 + 103.65 + 49.98)

    def test_epargne_regroupee(self):
        names = {x["name"] for x in self.r["saving"]["items"]}
        self.assertEqual(names, {"Livret LDDS", "Épargne programmée", "Saveback + arrondis"})
        prog = next(x for x in self.r["saving"]["items"] if x["name"] == "Épargne programmée")
        self.assertEqual(prog["amount"], 92.0)
        self.assertEqual(self.r["saving"]["rate"], round(self.r["saving"]["total"] / 2500 * 100))

    def test_virements_internes_et_dividendes_hors_budget(self):
        total = sum(x["amount"] for x in self.r["conso"]["detail"])
        self.assertNotIn(500.0, [x["amount"] for x in self.r["conso"]["detail"]])
        self.assertEqual(self.r["covered"]["total"], 500.0)
        self.assertEqual(round(total - self.r["conso"]["refunds"]["total"], 2), self.r["conso"]["total"])

    def test_remboursement_ami_deduit(self):
        self.assertEqual(self.r["conso"]["refunds"]["total"], 29.0)
        self.assertEqual(self.r["conso"]["refunds"]["items"][0]["name"], "Ami Un")

    def test_regroupements_et_categories(self):
        by = {x["name"]: x for x in self.r["conso"]["detail"]}
        self.assertEqual(by["Péages ASF"]["amount"], 26.6)
        self.assertEqual(by["Dons Fondation de France"]["amount"], 17.0)
        self.assertEqual(by["Essence"]["cat"], "Transport")
        self.assertEqual(by["Courses"]["amount"], 126.99)
        self.assertEqual(by["Claude Code Pro"]["amount"], 216.0)
        self.assertEqual(by["Ticketmaster"]["cat"], "Loisirs")
        self.assertIn("Loisirs divers (déduits)", by)  # rien n'est « non identifié »

    def test_reste_et_depassement(self):
        r = self.r
        self.assertEqual(r["left"], round(2500 - r["fixed"]["total"] - r["saving"]["total"] - r["conso"]["total"], 2))
        self.assertTrue(any(p["icon"] == "✅" for p in r["points"]))

    def test_section_semaine_seulement_le_lundi(self):
        self.assertIsNotNone(self.r["week"])  # le 28/09/2026 est un lundi
        self.assertEqual(self.r["week"]["top"][0]["name"], "Claude Code Pro")
        self.assertIsNone(report(CYCLE, date(2026, 9, 29))["week"])


if __name__ == "__main__":
    unittest.main()
