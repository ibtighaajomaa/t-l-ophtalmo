import os
import json
import torch
import torchvision.transforms as T
from PIL import Image
from torchvision.transforms.functional import InterpolationMode
from transformers import AutoModel, AutoTokenizer
from huggingface_hub import snapshot_download

# Import your existing functions and classes from your script
# Assuming you saved your previous code in a file named `report_generator.py`
from report_generator import generate_report, _extract_json 

# ---------------------------------------------------------
# 1. Image Preprocessing for VOLMO-2B (InternVL Architecture)
# ---------------------------------------------------------
def build_transform(input_size=448):
    IMAGENET_MEAN = (0.485, 0.456, 0.406)
    IMAGENET_STD = (0.229, 0.224, 0.225)
    transform = T.Compose([
        T.Lambda(lambda img: img.convert('RGB') if img.mode != 'RGB' else img),
        T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD)
    ])
    return transform

# ---------------------------------------------------------
# 2. VOLMO-2B Inference Function
# ---------------------------------------------------------
def analyze_image_with_volmo(image_path: str, model_path: str) -> dict:
    print("Loading VOLMO-2B model to GPU...")
    # Load Tokenizer and Model (trust_remote_code is required for InternVL architectures)
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        trust_remote_code=True
    ).eval().cuda()

    # Prepare Image
    print(f"Processing image: {image_path}")
    transform = build_transform()
    image = Image.open(image_path)
    
    # VOLMO expects pixel values shaped properly for its vision encoder
    pixel_values = transform(image).unsqueeze(0).to(torch.bfloat16).cuda()

    # Strict Prompt to force VOLMO to match your expected JSON structure
    prompt = """Analyze this retinal fundus image as an expert ophthalmologist. 
    Output ONLY a valid JSON object matching exactly this structure, with no additional text:
    {
      "dr_classification": {"grade": "string", "confidence": 0.95, "probabilities": [{"label": "string", "score": 0.95}]},
      "lesions": {"microaneurysms": 0, "hemorrhages": 0, "exudates": 0, "coverage_pct": 0.0},
      "glaucoma": {"vcdr": 0.0, "risk": "string", "disc_area_px": 0, "cup_area_px": 0},
      "vessels": {"coverage_pct": 0.0}
    }
    If a specific metric cannot be quantified, estimate it based on clinical presentation or output null."""

    print("Running VOLMO-2B Inference...")
    generation_config = dict(max_new_tokens=1024, do_sample=False)
    
    # Generate the text response
    response = model.chat(tokenizer, pixel_values, prompt, generation_config)
    
    # Use your existing extractor to pull the JSON block out of the string
    return _extract_json(response)


# ---------------------------------------------------------
# 3. Main Execution Workflow
# ---------------------------------------------------------
if __name__ == "__main__":
    # Ensure your OpenRouter API key is set
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("WARNING: OPENROUTER_API_KEY environment variable is not set.")
        # os.environ["OPENROUTER_API_KEY"] = "your_key_here"

    # Step A: Download / Locate VOLMO-2B
    print("Checking model files...")
    local_model_path = snapshot_download(repo_id="Yale-BIDS-Chen/VOLMO-2B")
    
    # Step B: Set patient details and image
    patient_id = "PAT-2026-0695"
    image_file = "sample_fundus.jpg" # Make sure this file exists in your directory
    
    try:
        # Step C: Get JSON data from the Image via VOLMO
        volmo_json_data = analyze_image_with_volmo(image_file, local_model_path)
        print("\n--- VOLMO Output Extracted ---")
        print(json.dumps(volmo_json_data, indent=2))
        
        # Step D: Pass the JSON directly into your OpenRouter formatting script
        print("\nSending data to Nemotron to format the final clinical report...")
        final_report = generate_report(report_data=volmo_json_data, patient_id=patient_id)
        
        # Step E: Save the final HTML output
        output_filename = f"report_{patient_id}.html"
        
        # Wrap it in basic HTML styling for readability
        html_wrapper = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Rapport - {patient_id}</title>
            <style>
                body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; color: #333; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #f8f9fa; }}
                h2 {{ color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 10px; margin-top: 30px; }}
                ul {{ background: #f8f9fa; padding: 20px 40px; border-radius: 8px; }}
            </style>
        </head>
        <body>
            <h1>Rapport Ophtalmologique</h1>
            {final_report['report_html']}
        </body>
        </html>
        """
        
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(html_wrapper)
            
        print(f"\nSuccess! Open {output_filename} in your web browser.")

    except Exception as e:
        print(f"Pipeline Failed: {e}")