#railway builds this from the embed/ folder (Root Directory embed), so every
#path below is relative to it and nothing else in the repo is in the context.
FROM python:3.12-slim

WORKDIR /app

#the weights go INTO THE IMAGE, which is the point: railway's serverless setting
#stops the container rather than deleting it, and a wake that had to download
#1.25gb first would put that in front of somebody's page load. it also means a
#running service never needs the network, which is what lets it idle to sleep.
#
#BEFORE the pip layers, and fetch_model.py is stdlib only so it can be: a layer
#rebuilds everything after it, so a requirements change would download 1.25gb again
COPY model_release.json fetch_model.py ./
RUN python fetch_model.py --dest /model

#the cpu wheel FIRST and from pytorch's own index, or pip pulls a 2gb+ cuda
#build that no railway container can use. same version as ingest/requirements.txt
RUN pip install --no-cache-dir torch==2.12.1 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV EMBED_MODEL_DIR=/model \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1

#ONE worker and ONE thread. the model is 1.25gb and a second worker holds a
#second copy; torch already uses every core for one encode, so a second thread
#would split them rather than double the throughput. requests queue, and a
#20 line card measured 131ms warm.
#
#[::] because railway's private network is ipv6. the 120s timeout is the
#gunicorn arbiter's, above the ~3s load and well above any single encode
CMD gunicorn --bind [::]:$PORT --workers 1 --threads 1 --timeout 120 app:app
