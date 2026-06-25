-- Orthanc Lua script: on_stable_study
-- Called by Orthanc when a study becomes stable (all instances received).
-- Posts to the Django worklist webhook to auto-sync new studies
-- into the worklist without requiring manual "Sync Orthanc".

function OnStableStudy(studyId)
    local webhook_url = "http://backend:8001/api/exams/orthanc-webhook/"
    local body = '{"ID":"' .. studyId .. '"}'

    local ok, resp = pcall(HttpPost, webhook_url, body, "application/json")

    if ok then
        Print("[OnStableStudy] Study " .. studyId .. " synced to worklist: " .. resp)
    else
        Print("[OnStableStudy] Study " .. studyId .. " webhook failed: " .. tostring(resp))
    end
end

Print("[Lua] on_stable_study.lua loaded — auto-sync enabled for new studies")
