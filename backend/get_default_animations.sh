#!/bin/bash

# Define the list of garments
garments=(
    "tank" "longsleeve" "pants_shorter" "pants" "shorts" "shortsleeve"
    "tight_dress" "tshirt_unzipped"
)

# poses=("apose" "walking" "jumping" "gymnastics")
poses=("sideflip")

conda init
conda deactivate
conda activate hood

# Iterate through the list of poses and garments
for pose in "${poses[@]}"
do
    for garment in "${garments[@]}"
    do
        # Run the Python command with the current garment
        echo "Running simulation for garment: $garment"
        # Construct the command as a string first
        if [ "$pose" = "apose" ]; then
            cmd="python ../../HOOD/get_simulation.py --body_dim_to_smpl_model_dir=../../HOOD/body_dim_to_smpl --gender=MALE --pose=$pose --garment_name=$garment --out_file=animations/default/$garment/$pose.glb"
        else
            cmd="python ../../HOOD/get_simulation.py --body_dim_to_smpl_model_dir=../../HOOD/body_dim_to_smpl --gender=MALE --pose=$pose --garment_name=$garment --out_file=animations/default/$garment/$pose.mp4"
        fi

        # Print the command to verify it
        echo "Executing: $cmd"
        $cmd
    done
done

echo "All simulations complete!"
