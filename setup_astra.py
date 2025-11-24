from astrapy import DataAPIClient
import os

client = DataAPIClient("AstraCS:TkatfvQRZriQnJaIwoDnUHLy:21a34927731e40ca3ffae13e620ed34d1c15082df267f17150eb441b6f84d717")
db = client.get_database_by_api_endpoint("https://44ca05b4-bdeb-4d0b-9aa0-df11303d8ca6-us-east1.apps.astra.datastax.com")
# Create basic collection
try:
    collection = db.create_collection("emails")
    print("✅ Collection 'emails' created successfully!")
except Exception as e:
    # If collection already exists, just get it
    collection = db.get_collection("emails")
    print("✅ Using existing 'emails' collection!")

print("ℹ️  Ready to load emails (with size optimizations)")