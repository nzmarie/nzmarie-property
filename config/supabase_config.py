from datetime import datetime
import os
import logging
import json
from utils.address_helper import get_canonical_address
from utils.database import db

# Set up logging
logger = logging.getLogger(__name__)

class SupabaseResponseShim:
    def __init__(self, data):
        self.data = data

class TableShim:
    def __init__(self, table_name):
        self.table_name = table_name
        self.filters = {}
        self._limit = None
        self._pending_op = "select"
        self._pending_data = None

    def select(self, columns="*"):
        self._pending_op = "select"
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, l):
        self._limit = l
        return self

    def order(self, column, desc=False):
        # Placeholder for order method
        return self

    def upsert(self, data, on_conflict='id'):
        self._pending_op = "upsert"
        self._pending_data = data
        return self

    def insert(self, data):
        self._pending_op = "insert"
        self._pending_data = data
        return self

    def update(self, data):
        self._pending_op = "update"
        self._pending_data = data
        return self

    def delete(self):
        self._pending_op = "delete"
        return self

    def neq(self, column, value):
        # We'll store neq filters separately or handle them in _build_where
        if not hasattr(self, 'neq_filters'):
            self.neq_filters = {}
        self.neq_filters[column] = value
        return self

    def is_(self, column, value):
        if not hasattr(self, 'is_filters'):
            self.is_filters = {}
        self.is_filters[column] = value
        return self
    
    def is_not(self, column, value):
        if not hasattr(self, 'is_not_filters'):
            self.is_not_filters = {}
        self.is_not_filters[column] = value
        return self

    def gt(self, column, value):
        if not hasattr(self, 'gt_filters'):
            self.gt_filters = {}
        self.gt_filters[column] = value
        return self
    
    def gte(self, column, value):
        if not hasattr(self, 'gte_filters'):
            self.gte_filters = {}
        self.gte_filters[column] = value
        return self

    def lt(self, column, value):
        if not hasattr(self, 'lt_filters'):
            self.lt_filters = {}
        self.lt_filters[column] = value
        return self

    def lte(self, column, value):
        if not hasattr(self, 'lte_filters'):
            self.lte_filters = {}
        self.lte_filters[column] = value
        return self

    def ilike(self, column, value):
        if not hasattr(self, 'ilike_filters'):
            self.ilike_filters = {}
        self.ilike_filters[column] = value
        return self

    def execute(self):
        if self._pending_op == "select":
            return self._execute_select()
        elif self._pending_op == "update":
            return self._execute_update()
        elif self._pending_op == "insert":
            return self._execute_insert()
        elif self._pending_op == "upsert":
            return self._execute_upsert()
        elif self._pending_op == "delete":
            return self._execute_delete()
        return SupabaseResponseShim([])

    def _execute_select(self):
        query = f"SELECT * FROM {self.table_name}"
        where_sql, where_params = self._build_where()
        if where_sql:
            query += " " + where_sql
        
        if self._limit:
            query += f" LIMIT {self._limit}"
            
        rows = db.query(query, where_params)
        return SupabaseResponseShim(rows if rows else [])

    def _execute_upsert(self):
        data = self._pending_data
        if not isinstance(data, list):
            data = [data]
        if not data:
            return SupabaseResponseShim([])

        columns = list(data[0].keys())
        placeholders = ", ".join(["%s"] * len(columns))
        # Build ON CONFLICT / DO UPDATE clause for CockroachDB
        update_cols = [c for c in columns if c != 'id']
        update_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
        sql = (
            f"INSERT INTO {self.table_name} ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {update_clause}"
        )
        params_list = [list(item.values()) for item in data]
        db.execute_batch(sql, params_list)
        return SupabaseResponseShim(data)

    def _execute_insert(self):
        data = self._pending_data
        if isinstance(data, list):
            results = []
            for item in data:
                cols = list(item.keys())
                placeholders = ["%s"] * len(cols)
                sql = f"INSERT INTO {self.table_name} ({', '.join(cols)}) VALUES ({', '.join(placeholders)}) RETURNING *"
                try:
                    rows = db.query(sql, list(item.values()))
                    if rows: results.extend(rows)
                except Exception as e:
                    if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                        raise e # Let the caller handle duplicates if they want
                    raise e
            return SupabaseResponseShim(results)

        columns = list(data.keys())
        placeholders = ["%s"] * len(columns)
        sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({', '.join(placeholders)}) RETURNING *"
        try:
            res = db.query(sql, list(data.values()))
            return SupabaseResponseShim(res)
        except Exception as e:
            if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                raise e # Let the caller handle duplicates if they want
            raise e

    def _execute_update(self):
        data = self._pending_data
        columns = list(data.keys())
        values = list(data.values())
        set_clauses = [f"{col} = %s" for col in columns]
        
        query = f"UPDATE {self.table_name} SET {', '.join(set_clauses)}"
        params = values
        
        where_sql, where_params = self._build_where()
        if where_sql:
            query += " " + where_sql
            params += where_params
            
        db.execute(query, params)
        return SupabaseResponseShim([data])

    def _execute_delete(self):
        query = f"DELETE FROM {self.table_name}"
        where_sql, where_params = self._build_where()
        if where_sql:
            query += " " + where_sql
        
        db.execute(query, where_params)
        return SupabaseResponseShim([{"status": "deleted"}])

    def _build_where(self):
        clauses = []
        params = []
        if hasattr(self, 'filters') and self.filters:
            for col, val in self.filters.items():
                clauses.append(f"{col} = %s")
                params.append(val)
        
        if hasattr(self, 'neq_filters') and self.neq_filters:
            for col, val in self.neq_filters.items():
                clauses.append(f"{col} != %s")
                params.append(val)
        
        if hasattr(self, 'is_filters') and self.is_filters:
            for col, val in self.is_filters.items():
                if val is None or str(val).lower() == 'null':
                    clauses.append(f"{col} IS NULL")
                else:
                    clauses.append(f"{col} IS %s")
                    params.append(val)
        
        if hasattr(self, 'is_not_filters') and self.is_not_filters:
            for col, val in self.is_not_filters.items():
                if val is None or str(val).lower() == 'null':
                    clauses.append(f"{col} IS NOT NULL")
                else:
                    clauses.append(f"{col} IS NOT %s")
                    params.append(val)

        if hasattr(self, 'gt_filters') and self.gt_filters:
            for col, val in self.gt_filters.items():
                clauses.append(f"{col} > %s")
                params.append(val)

        if hasattr(self, 'gte_filters') and self.gte_filters:
            for col, val in self.gte_filters.items():
                clauses.append(f"{col} >= %s")
                params.append(val)

        if hasattr(self, 'lt_filters') and self.lt_filters:
            for col, val in self.lt_filters.items():
                clauses.append(f"{col} < %s")
                params.append(val)

        if hasattr(self, 'lte_filters') and self.lte_filters:
            for col, val in self.lte_filters.items():
                clauses.append(f"{col} <= %s")
                params.append(val)

        if hasattr(self, 'ilike_filters') and self.ilike_filters:
            for col, val in self.ilike_filters.items():
                clauses.append(f"{col} ILIKE %s")
                params.append(val)
        
        if not clauses:
            return "", []
        
        return "WHERE " + " AND ".join(clauses), params

class SupabaseShim:
    """A minimal shim to mimic supabase-py client using CockroachDB"""
    def table(self, table_name):
        return TableShim(table_name)

    def from_(self, table_name):
        return self.table(table_name)

def create_supabase_client() -> SupabaseShim:
    """Return a shim that looks like Supabase client but talks to CockroachDB"""
    return SupabaseShim()

# --- Original Helper Functions (Re-implemented using db) ---

def clean_price(price_str):
    if price_str is None: return None
    if isinstance(price_str, (int, float)): return price_str
    try:
        return float(str(price_str).replace('$', '').replace(',', '').strip())
    except:
        return None

import uuid

def clean_property_data(property_data):
    price_fields = ['last_sold_price', 'capital_value', 'land_value', 'improvement_value']
    for field in price_fields:
        if field in property_data:
            property_data[field] = clean_price(property_data[field])
    if 'address' in property_data:
        property_data['address_fingerprint'] = get_canonical_address(property_data['address'])
        
    if 'id' not in property_data:
        # Generate a deterministic ID based on address_fingerprint (which has a UNIQUE constraint)
        seed_string = property_data.get('address_fingerprint') or property_data.get('property_url') or property_data.get('address') or str(uuid.uuid4())
        property_data['id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, seed_string))
        
    return property_data

def insert_property_and_history(property_data: dict, history_data: list) -> bool:
    try:
        cleaned = clean_property_data(property_data)
        
        # We don't use the text-based property_history anymore, we insert it structurally
        if 'property_history' in cleaned:
            del cleaned['property_history']
        
        # Use INSERT ON CONFLICT for address_fingerprint to avoid unique constraint violations
        columns = list(cleaned.keys())
        placeholders = ["%s"] * len(columns)
        update_cols = [c for c in columns if c not in ('id', 'address_fingerprint')]
        update_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
        
        sql = (
            f"INSERT INTO properties ({', '.join(columns)}) "
            f"VALUES ({', '.join(placeholders)}) "
            f"ON CONFLICT (address_fingerprint) DO UPDATE SET {update_clause} "
            f"RETURNING id"
        )
        
        # Get the actual ID from the DB (either inserted or updated)
        res = db.query(sql, list(cleaned.values()))
        if not res:
            return False
            
        property_id = res[0]['id']
        
        # Insert History Events structurally
        if history_data and isinstance(history_data, list):
            history_sql = """
                INSERT INTO property_history_events 
                (property_id, event_date, event_type, price, description, interval_since_last) 
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (property_id, event_date, description) DO NOTHING
            """
            
            history_params = []
            for event in history_data:
                date_str = event.get('event_date')
                if not date_str:
                    continue
                    
                desc = event.get('event_description', '')
                interval = event.get('interval_since_last_event', '')
                
                # Simple heuristic to extract event_type and price from description
                event_type = 'Unknown'
                price = None
                
                desc_lower = desc.lower()
                if 'sold' in desc_lower:
                    event_type = 'Sold'
                elif 'listed' in desc_lower:
                    event_type = 'Listed'
                elif 'built' in desc_lower:
                    event_type = 'Built'
                    
                # Extract price if it exists (e.g. "Sold for $398,000")
                if '$' in desc:
                    try:
                        price_str = desc.split('$')[1].split(' ')[0].replace(',', '')
                        if price_str.isdigit():
                            price = float(price_str)
                    except:
                        pass
                
                # Format date string to YYYY-MM-DD if possible, else rely on CockroachDB to parse
                # Playwright returns things like "15 Jan 2014" or "2016"
                if len(date_str) == 4 and date_str.isdigit():
                    date_str = f"{date_str}-01-01" # Default to Jan 1st for year-only dates
                    
                history_params.append([
                    property_id, 
                    date_str, 
                    event_type, 
                    price, 
                    desc, 
                    interval
                ])
                
            if history_params:
                db.execute_batch(history_sql, history_params)
                
        return True
    except Exception as e:
        logger.error(f"Error in insert_property_and_history: {e}")
        return False

def check_property_exists(address: str) -> bool:
    try:
        res = db.query("SELECT id FROM properties WHERE address = %s LIMIT 1", (address,))
        return len(res) > 0 if res else False
    except:
        return False

def insert_real_estate(address: str, status: str, latitude: float = None, longitude: float = None) -> bool:
    try:
        db.execute("INSERT INTO real_estate (address, address_fingerprint, status, latitude, longitude) VALUES (%s, %s, %s, %s, %s)", 
                   (address, get_canonical_address(address), status, latitude, longitude))
        return True
    except Exception as e:
        if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
            return False
        raise

def insert_real_estate_rent(address: str, status: str, latitude: float = None, longitude: float = None) -> bool:
    try:
        fingerprint = get_canonical_address(address)
        db.execute(
            """
            INSERT INTO real_estate_rent (address, address_fingerprint, status, latitude, longitude)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (address_fingerprint) DO UPDATE SET
                status = EXCLUDED.status,
                latitude = COALESCE(EXCLUDED.latitude, real_estate_rent.latitude),
                longitude = COALESCE(EXCLUDED.longitude, real_estate_rent.longitude)
            """,
            (address, fingerprint, status, latitude, longitude)
        )
        return True
    except Exception as e:
        if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
            return False
        raise

# Aliases for compatibility
create_client = create_supabase_client
Client = SupabaseShim

def upsert_real_estate_detail(data: dict) -> bool:
    try:
        if 'address' in data:
            data['address_fingerprint'] = get_canonical_address(data['address'])
        columns = list(data.keys())
        placeholders = ["%s"] * len(columns)
        sql = f"UPSERT INTO real_estate ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        db.execute(sql, list(data.values()))
        return True
    except Exception as e:
        logger.error(f"Error upserting real_estate: {e}")
        return False

def upsert_real_estate_rent_detail(data: dict) -> bool:
    try:
        if 'address' in data:
            data['address_fingerprint'] = get_canonical_address(data['address'])
        columns = list(data.keys())
        placeholders = ["%s"] * len(columns)
        sql = f"UPSERT INTO real_estate_rent ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        db.execute(sql, list(data.values()))
        return True
    except Exception as e:
        logger.error(f"Error upserting real_estate_rent: {e}")
        return False
