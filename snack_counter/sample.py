"""A small sample company used by the tests, the demo and the web app:
two offices, three volunteers each, one admin each, one non-volunteer."""
from decimal import Decimal

from .models import Employee, Office


def make_offices() -> dict:
    return {
        "OSL": Office("OSL", "NOK", Decimal("6000"), Decimal("300"), Decimal("1200"),
                      "Europe/Oslo", "#snacks-oslo", "osl-admin"),
        "BLR": Office("BLR", "INR", Decimal("15000"), Decimal("500"), Decimal("3000"),
                      "Asia/Kolkata", "#snacks-blr", "blr-admin"),
    }


def make_employees() -> dict:
    people = [
        Employee("ola", "Ola", "OSL", True), Employee("kari", "Kari", "OSL", True),
        Employee("nils", "Nils", "OSL", True), Employee("osl-admin", "Oslo admin", "OSL"),
        Employee("asha", "Asha", "BLR", True), Employee("ravi", "Ravi", "BLR", True),
        Employee("meera", "Meera", "BLR", True), Employee("blr-admin", "Blr admin", "BLR"),
        Employee("guest", "Not a volunteer", "OSL"),
    ]
    return {p.id: p for p in people}
