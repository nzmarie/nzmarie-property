#!/usr/bin/env python3
"""
Migration: Add images column to properties table
Date: 2026-07-08
Description: Add JSONB column to store property images array
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from utils.database import db

def run_migration():
    """Add images column if it doesn't exist"""
    print("Running migration: Add images column to properties table")
    
    try:
        # Check if column exists
        check_sql = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'properties' 
            AND column_name = 'images'
        """
        
        result = db.query(check_sql)
        
        if result:
            print("✓ Column 'images' already exists. Skipping migration.")
            return
        
        # Add column
        alter_sql = """
            ALTER TABLE properties 
            ADD COLUMN IF NOT EXISTS images JSONB
        """
        
        db.execute(alter_sql)
        print("✓ Successfully added 'images' column to properties table")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        raise

if __name__ == "__main__":
    run_migration()
