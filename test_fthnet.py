import sys
import os

sys.path.append(os.path.join(os.getcwd(), 'backend'))

from ophtalmo.fthnet_predictor import FTHNetPredictor
predictor = FTHNetPredictor()
print("Successfully initialized predictor!")
