#!/usr/bin/env python3
"""
SV2 Linux Bridge - Authentication Bridge for Synthesizer V Studio 2
Enables OAuth login for SV2 running in Wine/Bottles on Linux
"""

import argparse
import sys
import os
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))


def main():
    """Main entry point - forwards to auth bridge"""
    from auth_bridge.server import main as auth_main
    return asyncio.run(auth_main())


if __name__ == "__main__":
    sys.exit(main() or 0)
