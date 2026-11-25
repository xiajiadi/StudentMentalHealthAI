#!/usr/bin/env bash
# Apply a reviewed workspace-only bundle to the existing synthetic demo.
set -euo pipefail
umask 022

action=${1:?stage, activate, publish or rollback}
build=${2:?release identifier}
[[ $build =~ ^[a-z0-9-]{6,64}$ ]]
base=/opt/psynova-school-demo
releases=$base/workspace-agent-releases
release=$releases/$build
backend=$release/backend
runtime=$release/runtime
web=$base/web-releases/$build
backend_unit=psynova-school-demo.service
runtime_unit=psynova-school-llm.service
backend_conf=/etc/systemd/system/$backend_unit.d/90-workspace-agent.conf
runtime_conf=/etc/systemd/system/$runtime_unit.d/90-workspace-agent.conf

[[ $(id -u) -eq 0 ]]

wait_ready() {
    local url=$1
    for ((attempt=0; attempt<35; attempt++)); do
        if curl -fsS --max-time 2 "$url" >/dev/null; then return 0; fi
        sleep 2
    done
    return 1
}

swap_web() {
    local target=$1 temporary=$base/.web-$build
    [[ -f $target/index.html && -L $base/web ]]
    ln -s "$target" "$temporary"
    mv -Tf "$temporary" "$base/web"
}

rollback() {
    if [[ $(readlink -f "$base/web") == "$web" ]]; then
        swap_web "$(cat "$release/previous-web")"
    fi
    for path in "$backend_conf" "$runtime_conf"; do
        if [[ -f $path ]] && grep -Fq "$release/" "$path"; then rm -- "$path"; fi
    done
    systemctl daemon-reload
    systemctl restart "$runtime_unit"
    wait_ready http://127.0.0.1:8160/health/ready
    systemctl restart "$backend_unit"
    wait_ready http://127.0.0.1:8088/health/ready
}

case "$action" in
    stage)
        bundle=$(realpath "${3:?bundle directory}")
        [[ ! -e $release && ! -e $web ]]
        [[ ! -e $backend_conf && ! -e $runtime_conf && -L $base/web ]]
        previous_backend=$(systemctl show "$backend_unit" -p WorkingDirectory --value)
        previous_llm=$(systemctl show "$runtime_unit" -p WorkingDirectory --value)
        previous_web=$(readlink -f "$base/web")
        [[ $previous_backend == "$base"/* && $previous_llm == "$base"/* && $previous_web == "$base"/web-releases/* ]]
        mkdir -p "$release" "$runtime"
        printf '%s\n' "$previous_backend" > "$release/previous-backend"
        printf '%s\n' "$previous_web" > "$release/previous-web"
        printf '%s\n' "$previous_llm" > "$release/previous-llm"
        cp -a "$previous_backend" "$backend"
        cp -a "$previous_llm" "$runtime/06_llm-runtime"
        cp -a "$base/release/13_deployment" "$runtime/13_deployment"
        # Previous overlays were built on Windows and can contain CRLF Python files.
        for file in \
            "$backend/09_backend/src/smhai_backend/app_factory.py" \
            "$backend/09_backend/src/smhai_backend/core/config.py" \
            "$backend/09_backend/src/smhai_backend/domains/workspace_agent.py" \
            "$backend/09_backend/src/smhai_backend/integrations/llm.py" \
            "$backend/13_deployment/school_backend_linux.py" \
            "$runtime/06_llm-runtime/src/llm_runtime/providers/deepseek.py" \
            "$runtime/13_deployment/school_deepseek_independent_runtime.py"; do
            sed -i 's/\r$//' "$file"
        done
        patch -d "$backend" --batch --forward --fuzz=0 -p1 < "$bundle/backend.patch"
        patch -d "$runtime" --batch --forward --fuzz=0 -p1 < "$bundle/model.patch"
        "$base/venv/bin/python" -m compileall -q "$backend/09_backend/src" "$backend/13_deployment"
        "$base/services/llm/venv/bin/python" -m compileall -q "$runtime/06_llm-runtime/src"
        mkdir "$web"
        tar --extract --gzip --file "$bundle/web.tar.gz" --directory "$web" --no-same-owner --no-same-permissions
        [[ -f $web/index.html && -d $web/assets ]]
        cp -an "$previous_web/assets/." "$web/assets/"
        printf '%s\n' "$build" > "$web/workspace-agent-release.txt"
        touch "$release/staged"
        ;;
    activate)
        [[ -f $release/staged && -f $web/index.html ]]
        [[ ! -e $backend_conf && ! -e $runtime_conf ]]
        trap 'rollback' ERR
        cat > "$runtime_conf" <<EOF
[Service]
WorkingDirectory=$runtime/06_llm-runtime
Environment=PYTHONPATH=$runtime/13_deployment:$runtime/06_llm-runtime/src
EOF
        cat > "$backend_conf" <<EOF
[Service]
WorkingDirectory=$backend
Environment=PYTHONPATH=$backend/13_deployment:$backend/09_backend/src:$backend/11_database
Environment=PSYNOVA_WORKSPACE_AGENT_STORE=/var/lib/psynova-workspace-agent/threads.sqlite3
StateDirectory=psynova-workspace-agent
StateDirectoryMode=0700
ExecStartPre=
ExecStartPre=$base/venv/bin/python $backend/13_deployment/school_backend_linux.py --repo-root $backend --preflight-only
ExecStart=
ExecStart=$base/venv/bin/python $backend/13_deployment/school_backend_linux.py --repo-root $backend
EOF
        systemctl daemon-reload
        systemctl restart "$runtime_unit"
        wait_ready http://127.0.0.1:8160/health/ready
        systemctl restart "$backend_unit"
        wait_ready http://127.0.0.1:8088/health/ready
        trap - ERR
        ;;
    publish)
        [[ $(systemctl show "$backend_unit" -p WorkingDirectory --value) == "$backend" ]]
        [[ $(systemctl show "$runtime_unit" -p WorkingDirectory --value) == "$runtime/06_llm-runtime" ]]
        swap_web "$web"
        ;;
    rollback)
        [[ -f $release/previous-web ]]
        rollback
        ;;
    *)
        exit 2
        ;;
esac
