let meta = #{
    name: "p632-remaining-close",
    description: "Fan out remaining Phase 6.3.2 P0 closes on the feature branch, then verify no GO claims",
    phases: [
        #{ title: "Implement", detail: "parallel remaining P0/honesty lanes" },
        #{ title: "Verify", detail: "adversarial check that GO was not invented" },
    ],
    when_to_use: "When packing remaining 6.3.2 P0/honesty work on grok/phase63-ci-source-closure without merging main",
};

let impl_schema = #{
    "type": "object",
    "required": ["sha", "files", "ok"],
    "properties": #{
        "sha": #{ "type": "string" },
        "files": #{ "type": "string" },
        "ok": #{ "type": "boolean" },
        "residual": #{ "type": "string" },
    },
};
let verify_schema = #{
    "type": "object",
    "required": ["real", "reason"],
    "properties": #{
        "real": #{ "type": "boolean" },
        "reason": #{ "type": "string" },
    },
};

let bans = "Hard bans: no GitHub Actions; no --legacy-peer-deps; do not invent COMPLETE/FRESH/READY/Phase7 GO/Mass GO; do not add YAML; do not unpark unique22; do not flip RECONSTITUTION_APPLY; do not unify leftover occupancy with comboEventGateOk; do not fake-split cost_models or options_225; do not hand-edit catalog_ids.ts; do not push origin/main; one logical concern = one commit. Python is .venv/bin/python 3.11. Repo /Users/taku/GitHub/quant-platform on grok/phase63-ci-source-closure.";

phase("Implement");
let lanes = [
    "BackfillPlanner must call plan_required_segments for tip-snapshot AM/earnings; no 32/200 month densify",
    "source_capability.py docstring must say plan_required_segments subsets official domain",
    "ingestion-premium identity runIds use crypto.randomUUID not Math.random; leave retry jitter",
    "all seven workers package.json have types script so verify_ci runs wrangler types --check",
    "verify_ci.sh validates evaluation-ir golden against schema.json not file presence only",
    "quant-ops-mcp tool strings report stored policy_version not frozen Coverage V2 words",
    "FeatureContext get_equity_master uses PIT official island from 2008-05-07; AM/earnings stay DEFER; do not add master to COMPLETE_21",
    "governed datasets without V3 contract load None; planner does not invent official domain",
];
let jobs = [];
let i = 0;
for lane in lanes {
    let p = bans;
    p += " Isolation worktree. TASK: ";
    p += lane;
    p += ". Read the code with read_file/grep before editing. Commit once. Return sha, files, ok, residual.";
    jobs.push(#{
        prompt: p,
        label: "impl-" + i.to_string(),
        capability_mode: "all",
        isolation_worktree: true,
        output_schema: impl_schema,
    });
    i += 1;
}
let results = parallel(jobs);

let landed = [];
for r in results {
    if r != () && r.success && r.output.ok == true && r.output.sha != () && r.output.sha != "" {
        landed.push(r.output);
    }
}
log(landed.len().to_string() + " of " + lanes.len().to_string() + " lanes reported ok");

phase("Verify");
let vjobs = [];
for item in landed {
    let vp = "Adversarially verify this implementer claim. Read the committed files. Set real=true only if (1) the change exists at sha ";
    vp += item.sha;
    vp += " (2) it does not invent COMPLETE/FRESH/READY/GO (3) it does not add YAML. files=";
    vp += item.files;
    vp += " residual=";
    if item.residual != () { vp += item.residual; } else { vp += ""; }
    vjobs.push(#{
        prompt: vp,
        label: "verify",
        capability_mode: "read-only",
        output_schema: verify_schema,
    });
}
let confirmed = [];
if vjobs.len() > 0 {
    let verdicts = parallel(vjobs);
    let j = 0;
    for v in verdicts {
        if v != () && v.success && v.output.real == true {
            confirmed.push(landed[j]);
        }
        j += 1;
    }
}

let report = "p632 remaining close: confirmed ";
report += confirmed.len().to_string();
report += " / landed ";
report += landed.len().to_string();
report += ". Do not merge PR until ci-aggregate posts. Phase 7 remains NO-GO.";
let path = write_scratch_file("report.md", report);
complete(#{ path: path, confirmed: confirmed.len(), landed: landed.len() });
