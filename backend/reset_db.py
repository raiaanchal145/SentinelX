"""
One-off dev utility: wipes ALL data from every SentinelX table (users,
organizations, assets, ...) while leaving the schema itself untouched --
no need to re-run alembic afterwards.

Run from the backend folder with your venv activated:

    python reset_db.py

It will ask for a typed confirmation before touching anything.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def main() -> None:
    answer = input(
        "This will permanently delete ALL rows from the SentinelX database "
        "(users, organizations, assets, everything). Type 'yes' to continue: "
    )
    if answer.strip().lower() != "yes":
        print("Aborted -- nothing was deleted.")
        return

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
            )
        )
        tables = [row[0] for row in result.fetchall()]

        if not tables:
            print("No tables found -- nothing to delete.")
            return

        quoted = ", ".join(f'"{t}"' for t in tables)
        await conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))

    print(f"Done. Cleared {len(tables)} table(s): {', '.join(tables)}")


if __name__ == "__main__":
    asyncio.run(main())
