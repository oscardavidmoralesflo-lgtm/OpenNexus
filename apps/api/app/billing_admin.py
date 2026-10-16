"""Operator commands for billing, run inside the API container.

    python -m app.billing_admin balance
    python -m app.billing_admin grant 25 "Welcome credit"
    python -m app.billing_admin grant -5 "Correction"
    python -m app.billing_admin plan growth active
"""

import sys
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from .database import new_session
from .models import Agency
from .services import billing


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("balance", "grant", "plan"):
        print(__doc__)
        return 2
    with new_session() as db:
        agencies = list(db.scalars(select(Agency)))
        if len(agencies) != 1:
            print(f"Expected one agency, found {len(agencies)}")
            return 1
        agency = agencies[0]
        if argv[0] == "balance":
            print(f"{agency.name}: USD {billing.balance(agency)} · plan {agency.plan or '-'} ({agency.subscription_status})")
            return 0
        if argv[0] == "grant":
            try:
                amount = Decimal(argv[1])
            except (IndexError, InvalidOperation):
                print("Usage: grant <amount> [description]")
                return 2
            transaction = billing.grant(db, agency.id, amount, " ".join(argv[2:]))
            print(f"Balance now USD {transaction.balance_after}")
            return 0
        if len(argv) < 2 or billing.plan_by_id(argv[1]) is None:
            print("Usage: plan <plan id> [status]; plans: " + ", ".join(p.id for p in billing.plans()))
            return 2
        agency.plan = argv[1]
        agency.subscription_status = argv[2] if len(argv) > 2 else "active"
        db.commit()
        print(f"Plan {agency.plan} ({agency.subscription_status})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
