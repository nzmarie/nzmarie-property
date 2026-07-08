#!/usr/bin/env python3
"""
Migration: Add latitude and longitude columns to properties table
Date: 2026-07-08
Description: Add DOUBLE PRECISION columns to store property coordinates
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from utils.database import db

def run_migration():
    """Add latitude and longitude columns if they don't exist"""
    print("Running migration: Add latitude and longitude columns to properties table")
    
    try:
        # Check if columns exist
        check_sql = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'properties' 
            AND column_name IN ('latitude', 'longitude')
        """
        
        result = db.query(check_sql)
        existing_columns = [row['column_name'] for row in result] if result else []
        
        if 'latitude' in existing_columns and 'longitude' in existing_columns:
            print("✓ Columns 'latitude' and 'longitude' already exist. Skipping migration.")
            return
        
        # Add latitude column if missing
        if 'latitude' not in existing_columns:
            alter_sql_lat = """
                ALTER TABLE properties 
                ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION
            """
            db.execute(alter_sql_lat)
            print("✓ Successfully added 'latitude' column to properties table")
        
        # Add longitude column if missing
        if 'longitude' not in existing_columns:
            alter_sql_lng = """
                ALTER TABLE properties 
                ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION
            """
            db.execute(alter_sql_lng)
            print("✓ Successfully added 'longitude' column to properties table")
        
        print("✓ Migration completed successfully")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        raise

if __name__ == "__main__":
    run_migration()
