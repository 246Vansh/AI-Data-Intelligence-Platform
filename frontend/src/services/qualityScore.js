// =========================================================
// DATA QUALITY SCORE (pure)
// =========================================================
//
// The health score the Quality screen has always shown, moved here
// unchanged so the top bar's quality pill and the Quality screen show
// the same number from one implementation: 100 minus a penalty per
// issue the backend reported (error 25, warning 10, info 3), clamped to
// 0-100. Tested with node --test (qualityScore.test.js).

export const SEVERITY_PENALTY = Object.freeze({ error: 25, warning: 10, info: 3 });

//
// Returns null when there is no audit to score (no response, or a
// response without an issues list) - "unknown" must never read as 100%.
export function healthScore(quality) {
    if (!quality || !Array.isArray(quality.issues)) {
        return null;
    }
    const issues = quality.issues;
    let penalty = 0;
    for (const issue of issues) {
        penalty += SEVERITY_PENALTY[issue?.severity] ?? SEVERITY_PENALTY.info;
    }
    return Math.max(0, Math.min(100, 100 - penalty));
}

// The score's band, on the thresholds the Quality screen already used
// (>= 80 good, >= 60 fair, else poor).
export function scoreBand(score) {
    if (score === null || score === undefined) return "unknown";
    if (score >= 80) return "good";
    if (score >= 60) return "fair";
    return "poor";
}

export function severityCounts(quality) {
    const counts = { total: 0, error: 0, warning: 0, info: 0 };
    for (const issue of Array.isArray(quality?.issues) ? quality.issues : []) {
        counts.total += 1;
        const severity = ["error", "warning"].includes(issue?.severity) ? issue.severity : "info";
        counts[severity] += 1;
    }
    return counts;
}
