import json
import requests

BASE = "https://ark.wiki.gg/api.php"

def fetch_cargo(table, fields, where=None):
    params = {
        "action": "cargoquery",
        "format": "json",
        "tables": table,
        "fields": fields,
        "limit": "max"
    }
    if where:
        params["where"] = where

    r = requests.get(BASE, params=params)
    r.raise_for_status()
    return r.json()["cargoquery"]

def main():
    creatures = fetch_cargo(
        table="Creatures",
        fields="name,dlc,tameable,breedable"
    )

    creature_data = {}
    for row in creatures:
        c = row["title"]
        creature_data[c["name"]] = {
            "dlc": c["dlc"],
            "tameable": c["tameable"] == "Yes",
            "breedable": c["breedable"] == "Yes"
        }

    with open("data/creatures.json", "w") as f:
        json.dump(creature_data, f, indent=2)

    print(f"Saved {len(creature_data)} creatures")

if __name__ == "__main__":
    main()
