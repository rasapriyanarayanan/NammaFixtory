#!/usr/bin/env bash
# Start NammaFixtory at http://localhost:5000  (officer key: demo123, change with NAMMAFIXTORY_OFFICER_KEY)
cd "$(dirname "$0")"
exec python3 app.py
