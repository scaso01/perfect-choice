"""Pre-built criteria sets for common decision types."""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "job_offer": {
        "description": "Compare job offers",
        "criteria": [
            {"name": "Salary", "description": "Total compensation package", "is_cost": False},
            {"name": "Commute", "description": "Daily travel time", "is_cost": True},
            {"name": "Growth", "description": "Career advancement opportunities", "is_cost": False},
            {"name": "Culture", "description": "Team and work environment", "is_cost": False},
            {"name": "Benefits", "description": "Insurance, PTO, perks", "is_cost": False},
            {"name": "Stability", "description": "Company financial health and job security", "is_cost": False},
        ],
    },
    "apartment": {
        "description": "Compare apartments or rental properties",
        "criteria": [
            {"name": "Rent", "description": "Monthly cost", "is_cost": True},
            {"name": "Location", "description": "Proximity to work, transit, amenities", "is_cost": False},
            {"name": "Size", "description": "Square footage and layout", "is_cost": False},
            {"name": "Condition", "description": "Age, maintenance, appliances", "is_cost": False},
            {"name": "Parking", "description": "Available parking options", "is_cost": False},
            {"name": "Safety", "description": "Neighborhood safety and security", "is_cost": False},
        ],
    },
    "car": {
        "description": "Compare vehicles for purchase",
        "criteria": [
            {"name": "Price", "description": "Purchase price", "is_cost": True},
            {"name": "Fuel Economy", "description": "Miles per gallon or kWh efficiency", "is_cost": True},
            {"name": "Reliability", "description": "Expected maintenance and longevity", "is_cost": False},
            {"name": "Features", "description": "Tech, comfort, safety features", "is_cost": False},
            {"name": "Resale Value", "description": "Expected depreciation", "is_cost": False},
            {"name": "Insurance", "description": "Annual insurance cost", "is_cost": True},
        ],
    },
    "laptop": {
        "description": "Compare laptops or computers",
        "criteria": [
            {"name": "Price", "description": "Purchase cost", "is_cost": True},
            {"name": "Performance", "description": "CPU, RAM, storage speed", "is_cost": False},
            {"name": "Portability", "description": "Weight and size", "is_cost": True},
            {"name": "Battery Life", "description": "Hours of unplugged use", "is_cost": False},
            {"name": "Display", "description": "Screen quality and size", "is_cost": False},
            {"name": "Build Quality", "description": "Materials and durability", "is_cost": False},
        ],
    },
    "vacation": {
        "description": "Compare vacation destinations",
        "criteria": [
            {"name": "Cost", "description": "Total trip budget", "is_cost": True},
            {"name": "Travel Time", "description": "Duration of journey", "is_cost": True},
            {"name": "Activities", "description": "Things to see and do", "is_cost": False},
            {"name": "Weather", "description": "Expected climate conditions", "is_cost": False},
            {"name": "Safety", "description": "Destination safety for travelers", "is_cost": False},
            {"name": "Food", "description": "Dining quality and variety", "is_cost": False},
        ],
    },
    "college": {
        "description": "Compare colleges or universities",
        "criteria": [
            {"name": "Tuition", "description": "Annual cost of attendance", "is_cost": True},
            {"name": "Reputation", "description": "Academic ranking and prestige", "is_cost": False},
            {"name": "Location", "description": "City, climate, distance from home", "is_cost": False},
            {"name": "Programs", "description": "Strength of desired major", "is_cost": False},
            {"name": "Financial Aid", "description": "Scholarships and aid available", "is_cost": False},
            {"name": "Campus Life", "description": "Social scene, clubs, housing", "is_cost": False},
        ],
    },
}


def list_templates() -> list[str]:
    """Return available template names."""
    return list(TEMPLATES.keys())


def get_template(name: str) -> dict | None:
    """Get a template by name. Returns None if not found."""
    return TEMPLATES.get(name)


def match_template(title: str) -> str | None:
    """Try to match a decision title to a template by keyword."""
    title_lower = title.lower()
    keywords = {
        "job": "job_offer", "offer": "job_offer", "career": "job_offer",
        "apartment": "apartment", "rent": "apartment", "housing": "apartment", "house": "apartment",
        "car": "car", "vehicle": "car", "truck": "car",
        "laptop": "laptop", "computer": "laptop", "pc": "laptop",
        "vacation": "vacation", "trip": "vacation", "travel": "vacation",
        "college": "college", "university": "college", "school": "college",
    }
    for keyword, template_name in keywords.items():
        if keyword in title_lower:
            return template_name
    return None
