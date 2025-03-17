import requests
import re
import json
import logging
import pandas as pd
import numpy as np
import os
from datetime import datetime
import argparse
import ast

now = datetime.now()
timestamp = now.strftime("%Y%m%d_%H%M%S")

# # Set up logger
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     datefmt='%Y-%m-%d %H:%M:%S',
#     handlers=[
#         logging.FileHandler(f"size_recommender.log"),
#         logging.StreamHandler()
#     ]
# )

# logger = logging.getLogger(__name__)
# logger.info("Starting new session")

def get_diff(actual, lower, upper):
    if (lower is None) or (upper is None):
        return None
    if (lower <= actual) and (actual <= upper):
        return 0
    
    if abs(actual - lower) <= abs(actual - upper):
        return (lower - actual)
    else:
        return (upper - actual)

def row_avg(row):
    valid_values = [abs(x) for x in row if not np.isnan(x)]
    if valid_values:
        return sum(valid_values) / len(valid_values)
    else:
        return None

def get_size(size_guide_path, body_measurements, gender, category):
    # # Log info
    # logger.info("Finding sizing")
    # logger.info(f"Body measurements: {body_measurements}")

    size_df = pd.read_csv(size_guide_path)
    size_df = size_df[(size_df["gender"] == gender)]

    # size_guide_dimensions = ["height", "weight", "chest", "waist", "hip", "inseam"]
    # size_guide_to_body_map = {
    #     "height": "Height", 
    #     "weight": "Weight", 
    #     "chest": "Bust_girth", 
    #     "waist": "Waist_girth", 
    #     "hip": "Top_hip_girth", 
    #     "inseam" : "Inside_leg_height"
    # }
    size_guide_dimensions = ["height", "chest", "waist", "hip", "inseam"]
    size_guide_to_body_map = {
        "height": "height", 
        "chest": "bust", 
        "waist": "waist", 
        "hip": "hips", 
        "inseam" : "inseam"
    }

    # Change unit of body measurements from m to cm
    for key in body_measurements.keys():
        body_measurements[key] = body_measurements[key] * 100

    for size_dim, body_dim in size_guide_to_body_map.items():
        size_df[size_dim] = size_df.apply(lambda row: get_diff(body_measurements[body_dim], row[f"{size_dim}_lower"], row[f"{size_dim}_upper"]), axis=1)

    size_df["diff_average"] = size_df[size_guide_dimensions].apply(row_avg, axis=1)
    size_df = size_df.sort_values(by="diff_average", ascending=True).reset_index(drop=True)
    size_df["comment"] = ""

    MARGIN_FOR_SLIGHT = 5
    if category == "top":
        comment_dim_list = ["Chest", "Waist", "Hip"]
    elif category == "bottom":
        comment_dim_list = ["Waist", "Hip"]
    else: # category == "dress"
        comment_dim_list = ["Chest", "Waist", "Hip"]


    for i, row in size_df.iterrows():
        comment = []
        for dim in comment_dim_list:
            if (not np.isnan(row[dim.lower()])) and (row[dim.lower()] == 0):
                comment.append(f"{dim} area just right")
            elif (not np.isnan(row[dim.lower()])) and (row[dim.lower()] != 0):
                if row[dim.lower()] < 0:
                    if row[dim.lower()] < -MARGIN_FOR_SLIGHT:
                        comment.append(f"{dim} area maybe too tight")
                    else:
                        comment.append(f"{dim} area maybe slightly tight")
                else:
                    if row[dim.lower()] > MARGIN_FOR_SLIGHT:
                        comment.append(f"{dim} area maybe too large")
                    else:
                        comment.append(f"{dim} area maybe slightly large")
        
        if (not np.isnan(row["inseam"])) and (row["inseam"] != 0):
            comment.append(f"The item length is just right")
        elif (not np.isnan(row["inseam"])) and (row["inseam"] != 0):
            if row[dim.lower()] < 0:
                if row["inseam"] < -MARGIN_FOR_SLIGHT:
                    comment.append("The item maybe too short")
                else:
                    comment.append("The item maybe slightly short")
            else:
                if row["inseam"] > MARGIN_FOR_SLIGHT:
                    comment.append("The item maybe long")
                else:
                    comment.append("The item maybe slightly long")

        size_df.loc[i, "comment"] = ";".join(comment)

    best_size = size_df.loc[0, "size"]
    best_comment = size_df.loc[0, "comment"]

    return (best_size, best_comment)

if __name__ == "__main__":
    # Get body measurements from measure_avatar.js
    # Get gender and category info from product

    body_measurements = {
        "height": 1.867314042297201,
        "chest": 1.059210082087582,
        "waist": 0.8672310628809551,
        "hip": 1.0172857658818677,
        "shoulder_width": 0.37430697398954244,
        "sleeve_length": 0.46978631963034506,
        "inseam": 0.8836769375953112
    }

    gender = "male"
    category = "top"

    size, comment = get_size(body_measurements, gender, category)

    print(f"Recommended size: {size}")
    print(f"Comment: {comment}")