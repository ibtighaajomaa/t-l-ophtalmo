######################################################

FROM node:18.16.1-slim AS builder

RUN apt-get update && apt-get install -y git jq

WORKDIR /sources

# Clone OHIF Viewers v3.11.0
RUN git clone https://github.com/OHIF/Viewers.git && \
    cd /sources/Viewers && git checkout v3.11.0

# Clone MONAILabel for the OHIF plugin source
RUN git clone https://github.com/Project-MONAI/MONAILabel.git && \
    cd /sources/MONAILabel && git checkout 6ed8f8c

# Symlink monai-label extension and mode into OHIF source tree
RUN ln -s /sources/MONAILabel/plugins/ohifv3/extensions/monai-label /sources/Viewers/extensions/monai-label
RUN ln -s /sources/MONAILabel/plugins/ohifv3/modes/monai-label /sources/Viewers/modes/monai-label

# Copy iframe-bridge extension (worklist ↔ OHIF synchronization via postMessage)
COPY ohif/extensions/iframe-bridge /sources/Viewers/extensions/iframe-bridge

# Override MONAILabel plugin files with local modifications (AI Analysis features)
COPY MONAILabel/plugins/ohifv3/extensions/monai-label /sources/MONAILabel/plugins/ohifv3/extensions/monai-label
COPY MONAILabel/plugins/ohifv3/modes/monai-label /sources/MONAILabel/plugins/ohifv3/modes/monai-label

# Patch pluginConfig.json to register the monai-label extension and mode,
# and keep only desired modes (MONAI Label, Basic Viewer, Segmentation)
WORKDIR /sources/Viewers
RUN jq '.extensions += [{"packageName": "@ohif/extension-monai-label", "version": "3.0.0", "default": false}, {"packageName": "@ohif/extension-iframe-bridge", "version": "3.0.0", "default": false}] | .modes += [{"packageName": "@ohif/mode-monai-label", "version": "3.0.0", "default": false}] | .modes = [.modes[] | select(.packageName == "@ohif/mode-longitudinal" or .packageName == "@ohif/mode-segmentation" or .packageName == "@ohif/mode-monai-label")]' platform/app/pluginConfig.json > platform/app/pluginConfig.json.tmp && mv platform/app/pluginConfig.json.tmp platform/app/pluginConfig.json

# Reuse the MONAI AI Analysis panel as a third right-sidebar tab in /viewer.
COPY ohif/patches/longitudinal-ai-analysis.patch /tmp/longitudinal-ai-analysis.patch
RUN git apply --check /tmp/longitudinal-ai-analysis.patch && \
    git apply /tmp/longitudinal-ai-analysis.patch

# Patch isValidMode to accept all modalities (not just CT/MR)
RUN sed -i 's/valid: modalitiesArray.includes(.CT.) || modalitiesArray.includes(.MR.)/valid: true/' modes/monai-label/src/index.tsx

# Disable Service Worker (PWA) - remove InjectManifest from webpack config
RUN sed -i '/\/\/ Generate a service worker for fast local loads/,/\]),/d' platform/app/.webpack/webpack.pwa.js

# Disable Service Worker registration script (make it a no-op)
RUN echo -n > platform/app/public/init-service-worker.js

# Build
RUN yarn config set workspaces-experimental true
RUN yarn install
ENV QUICK_BUILD true
RUN yarn install
RUN QUICK_BUILD=true PUBLIC_URL=/ohif/ yarn run build

######################################################

FROM nginx:1.23

RUN mkdir /etc/nginx/enabled-sites
RUN mkdir /scripts

COPY ohif/ohif-static.conf /etc/nginx/enabled-sites/
ADD ohif/ohif-nginx-http.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /sources/Viewers/platform/app/dist /usr/share/nginx/html/
COPY ohif/default-app-config.js /usr/share/nginx/html/app-config.js
