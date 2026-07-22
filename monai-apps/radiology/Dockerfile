FROM projectmonai/monailabel:latest

RUN pip3 install --no-cache-dir \
    "numpy<2" \
    "opencv-python-headless<4.12" \
    "transformers<5" \
    segmentation_models_pytorch \
    tensorflow-cpu \
    h5py

# VascX is AGPL-3.0.  Keep MONAI's NumPy 1.x ABI for TensorFlow and install
# the inference package without its overly strict NumPy 2 metadata pin.
RUN pip3 install --no-cache-dir \
    "retinalysis-fundusprep==1.1.0" \
    "lightning>=2,<3" \
    "albumentations==1.3.1" \
    "simplejpeg>=1,<2" \
    "GPUtil>=1,<2" \
    "huggingface-hub>=0.32,<2" && \
    pip3 install --no-cache-dir --no-deps "retinalysis-inference==0.7.1" && \
    python3 -c "from rtnls_inference.ensembles import HeatmapRegressionEnsemble; from rtnls_fundusprep.preprocessor import FundusPreprocessor"
