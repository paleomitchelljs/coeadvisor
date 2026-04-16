/* Coe College Academic Advising Tool — Static Web App
   All logic runs client-side. DATA is loaded from data.js. */

// ─── Course utilities ────────────────────────────────────────────────────────

function normalize(code) {
  code = code.trim().toUpperCase().replace(/\s+/g, "");
  const m = code.match(/^([A-Z]+)-?(\d+[A-Z]*)$/);
  return m ? m[1] + "-" + m[2] : code;
}

function prefixOf(code) {
  const m = code.match(/^([A-Z]+)-/);
  return m ? m[1] : "";
}

function levelOf(code) {
  const m = code.match(/^[A-Z]+-(\d)/);
  return m ? parseInt(m[1]) * 100 : 0;
}

function isLab(code) { return /^[A-Z]+-\d+L$/.test(code); }
function isClinical(code) { return /^[A-Z]+-\d+C$/.test(code); }
function isAuxiliary(code) { return isLab(code) || isClinical(code); }

const MATH_PREFIXES = new Set(["MTH", "STA", "MAT"]);
const SCIENCE_PREFIXES = new Set(["BIO", "CHM", "PHY", "ESC", "ENS", "GEO"]);
function isMathCourse(code) { return MATH_PREFIXES.has(prefixOf(code)); }
function isScienceCourse(code) { return SCIENCE_PREFIXES.has(prefixOf(code)); }

function creditOf(code, overrides) {
  if (overrides && overrides[code] !== undefined) return overrides[code];
  return isAuxiliary(code) ? 0.2 : 1.0;
}

function totalCredits(taken, overrides) {
  let sum = 0;
  for (const c of taken) sum += creditOf(c, overrides);
  return sum;
}

function parseCourses(text) {
  const seen = new Set(), result = [];
  function add(code) {
    const n = normalize(code);
    if (n && !seen.has(n)) { seen.add(n); result.push(n); }
  }
  for (let raw of text.split(/[\n,;]+/)) {
    raw = raw.trim();
    if (!raw || raw.startsWith("#")) continue;
    const upper = raw.toUpperCase().replace(/\s+/g, "");
    const slash = upper.match(/^([A-Z]+-?)(\d+)\/(\d+[A-Z]*)$/);
    if (slash) {
      const pfx = slash[1].replace(/-$/, "");
      add(pfx + "-" + slash[2]);
      add(pfx + "-" + slash[3]);
      continue;
    }
    const tokens = raw.split(/\s+/);
    let i = 0;
    while (i < tokens.length) {
      const tok = tokens[i];
      if (i + 1 < tokens.length && /^[A-Za-z]+$/.test(tok) && /^\d+[A-Za-z]*$/.test(tokens[i+1])) {
        add(tok + "-" + tokens[i+1]);
        i += 2;
      } else {
        add(tok);
        i++;
      }
    }
  }
  return result;
}

// ─── Requirement checker ─────────────────────────────────────────────────────

const COMPLETE = "complete", PARTIAL = "partial", INCOMPLETE = "incomplete", MANUAL = "manual";

function codesSatisfied(codes, taken) {
  const norm = codes.map(normalize);
  const primary = norm.filter(c => !isAuxiliary(c));
  const found = norm.filter(c => taken.has(c));
  const sat = (primary.length > 0 && primary.some(c => taken.has(c)))
              || (primary.length === 0 && found.length > 0);
  return { sat, found };
}

function checkSection(section, taken) {
  const stype = section.type || "all";

  if (stype === "non_course")
    return { ...section, status: MANUAL, message: section.description || "Mark manually" };

  if (stype === "all") {
    let allOk = true;
    const items = (section.items || []).map(item => {
      const { sat, found } = codesSatisfied(item.codes || [], taken);
      if (!sat) allOk = false;
      return { ...item, satisfied: sat, found };
    });
    return { ...section, items, status: allOk ? COMPLETE : INCOMPLETE };
  }

  if (stype === "choose_one") {
    let anyOk = false;
    const options = (section.options || []).map(opt => {
      const codes = opt.codes || [];
      const norm = codes.map(normalize);
      const primary = norm.filter(c => !isAuxiliary(c));
      const sat = primary.length > 0
        ? primary.every(c => taken.has(c))
        : (norm.length > 0 && norm.some(c => taken.has(c)));
      if (sat) anyOk = true;
      return { ...opt, satisfied: sat };
    });
    return { ...section, options, status: anyOk ? COMPLETE : INCOMPLETE };
  }

  if (stype === "choose_n") {
    const n = section.n || 1;
    let count = 0;
    const items = (section.items || []).map(item => {
      const { sat, found } = codesSatisfied(item.codes || [], taken);
      if (sat) count++;
      return { ...item, satisfied: sat, found };
    });
    const status = count >= n ? COMPLETE : (count > 0 ? PARTIAL : INCOMPLETE);
    return { ...section, items, satisfied_count: count, status, message: `${count}/${n} selected` };
  }

  if (stype === "open_n") {
    const n = section.n || 1;
    const c = section.constraints || {};
    const pfxs = new Set(c.prefixes || []);
    const excl = new Set((c.exclude_codes || []).map(normalize));
    const minLvl = c.min_level || 0;
    const minCnt = c.min_level_count || 0;
    const levelIsFloor = minLvl && (!minCnt || minCnt >= n);
    const matching = [...taken].filter(x =>
      !isAuxiliary(x) && (!pfxs.size || pfxs.has(prefixOf(x))) && !excl.has(x)
      && (!levelIsFloor || levelOf(x) >= minLvl));
    const above = minLvl ? matching.filter(x => levelOf(x) >= minLvl).length : matching.length;
    const levelOk = minCnt ? above >= minCnt : true;
    const status = (matching.length >= n && levelOk) ? COMPLETE
      : matching.length > 0 ? PARTIAL : INCOMPLETE;
    const parts = [`${matching.length}/${n} electives`];
    if (minCnt) parts.push(`${above}/${minCnt} at ${minLvl}+ level`);
    return { ...section, matching, above_level: above, status, message: parts.join("; ") };
  }

  return { ...section, status: INCOMPLETE, message: "Unknown section type" };
}

function checkProgram(program, taken) {
  const sections = (program.sections || []).map(s => checkSection(s, taken));
  const countable = sections.filter(s => s.status !== MANUAL);
  const done = countable.filter(s => s.status === COMPLETE).length;
  return { program, sections, total: countable.length, complete: done };
}

function checkGE(ge, taken, dac, we) {
  const div = ge.divisional.sections;
  function divCourses(pfxs, maxPer) {
    maxPer = maxPer || 2;
    const pfxSet = new Set(pfxs);
    const byPfx = {};
    for (const c of [...taken].sort()) {
      if (isAuxiliary(c)) continue;
      const p = prefixOf(c);
      if (pfxSet.has(p)) (byPfx[p] = byPfx[p] || []).push(c);
    }
    const result = [];
    for (const p of Object.keys(byPfx).sort())
      result.push(...byPfx[p].slice(0, maxPer));
    return result;
  }

  const fa = divCourses(div.fine_arts.prefixes);
  const hum = divCourses(div.humanities.prefixes);
  const ns = divCourses(div.nat_sci_math.prefixes);
  const ss = divCourses(div.social_sciences.prefixes);

  const labPairs = [];
  for (const c of taken) {
    if (isLab(c)) {
      const lecture = c.replace(/L$/, "");
      if (taken.has(lecture)) labPairs.push([lecture, c]);
    }
  }

  const weFound = [...taken].filter(c =>
    !isAuxiliary(c) && (we.has(c) || c.endsWith("W") || c.endsWith("WE"))).sort();
  const dacFound = [...taken].filter(c => dac.has(c) && !isAuxiliary(c)).sort();
  const fysFound = [...taken].filter(c =>
    prefixOf(c) === "FYS" || ["FS-110","FS-111","FS-112"].includes(c));
  const prxFound = [...taken].filter(c => prefixOf(c) === "PRX");

  return {
    fine_arts: { label: "Fine Arts (\u22652 credits)", required: 2, courses: fa,
                 complete: fa.length >= 2, prefixes: div.fine_arts.prefixes },
    humanities: { label: "Humanities (\u22652 credits)", required: 2, courses: hum,
                  complete: hum.length >= 2, prefixes: div.humanities.prefixes },
    nat_sci_math: { label: "Nat. Sci. & Math (\u22651 credit)", required: 1, courses: ns.slice(0,1),
                    complete: ns.length >= 1, prefixes: div.nat_sci_math.prefixes },
    lab_science: { label: "Lab Science (\u22651 lecture+lab)", required: 1,
                   pairs: labPairs.slice(0,1), complete: labPairs.length >= 1 },
    social_sciences: { label: "Social Sciences (\u22652 credits)", required: 2, courses: ss,
                       complete: ss.length >= 2, prefixes: div.social_sciences.prefixes },
    fys: { label: "First Year Seminar (1)", required: 1, courses: fysFound,
           complete: fysFound.length >= 1 },
    we: { label: "Writing Emphasis (5 courses)", required: 5, courses: weFound,
          complete: weFound.length >= 5 },
    dac: { label: "Diversity Across Curriculum (2)", required: 2, courses: dacFound.slice(0,2),
           complete: dacFound.length >= 2 },
    practicum: { label: "Practicum (1)", required: 1, courses: prxFound,
                 complete: prxFound.length >= 1 },
  };
}

// ─── Trajectory data helper ──────────────────────────────────────────────────

function trajectoryInfo(majorCode, courseCode) {
  const maj = DATA.trajectory[majorCode];
  return maj ? maj[normalize(courseCode)] || null : null;
}

function electiveSuggestions(majorCode, exclude, n) {
  n = n || 12;
  const maj = DATA.trajectory[majorCode] || {};
  const rows = [];
  for (const [code, info] of Object.entries(maj)) {
    if (exclude.has(code)) continue;
    if ((info.tier === "elective" || info.tier === "common") && info.pct >= 0.15)
      rows.push([code, info]);
  }
  rows.sort((a, b) => b[1].pct - a[1].pct);
  return rows.slice(0, n);
}

// ─── Offerings index ────────────────────────────────────────────────────────

const OFFERING_TERM = {};

function buildOfferingsIndex() {
  const off = DATA.offerings || {};
  const terms = off.terms || {};
  const fallSet = new Set((terms.fall || {}).courses || []);
  const springSet = new Set((terms.spring || {}).courses || []);
  for (const c of fallSet) {
    OFFERING_TERM[c] = springSet.has(c) ? "both" : "fall";
  }
  for (const c of springSet) {
    if (!OFFERING_TERM[c]) OFFERING_TERM[c] = "spring";
  }
}

function semesterTerm(semNum) {
  return semNum % 2 === 1 ? "fall" : "spring";
}

function checkTermConflict(code, semNum) {
  if (!semNum) return null;
  const offering = OFFERING_TERM[code];
  if (!offering || offering === "both") return null;
  const term = semesterTerm(semNum);
  if (offering !== term) {
    const offeredIn = offering === "fall" ? "Fall" : "Spring";
    return `${code} is typically offered ${offeredIn} only`;
  }
  return null;
}

function termBadgeHTML(code) {
  const t = OFFERING_TERM[code];
  if (!t) return "";
  if (t === "fall") return '<span class="term-badge fall">F</span>';
  if (t === "spring") return '<span class="term-badge spring">S</span>';
  return '<span class="term-badge both">F/S</span>';
}

// ─── Suggested Plan builder ──────────────────────────────────────────────────

const PLAN_SEM_LABELS = {
  1: "Fall \u2014 Year 1",   2: "Spring \u2014 Year 1",
  3: "Fall \u2014 Year 2",   4: "Spring \u2014 Year 2",
  5: "Fall \u2014 Year 3",   6: "Spring \u2014 Year 3",
  7: "Fall \u2014 Year 4",   8: "Spring \u2014 Year 4",
};

const F2Y_SEM_NUM = { y1_fall: 1, y1_spring: 2, y2_fall: 3, y2_spring: 4 };

function buildSemesterSuggestions(semNum, allTaken, shownCodes, selectedProgs, geResult, majorCode, activePathways) {
  const items = [];
  const term = semesterTerm(semNum);

  // F2Y courses for semesters 1-4
  if (semNum <= 4) {
    const f2yEntries = findF2YEntries(selectedProgs, activePathways);
    const semKey = Object.entries(F2Y_SEM_NUM).find(([k, v]) => v === semNum);
    if (semKey) {
      for (const entry of f2yEntries) {
        const semData = (entry.semesters || {})[semKey[0]];
        if (!semData) continue;
        for (const cat of ["essential", "suggested"]) {
          for (const item of (semData[cat] || [])) {
            const code = normalize(item);
            if (!/^[A-Z]+-\d/.test(code)) continue;
            if (shownCodes.has(code)) continue;
            // Check term compatibility
            const off = OFFERING_TERM[code];
            if (off && off !== "both" && off !== term) continue;
            shownCodes.add(code);
            const done = allTaken.has(code);
            const traj = majorCode ? trajectoryInfo(majorCode, code) : null;
            items.push({
              code, display: code, category: cat,
              done, pct: traj ? traj.pct : null, trajSem: traj ? traj.sem : null,
            });
          }
        }
      }
    }
  }

  // FS-110 in semester 1
  if (semNum === 1) {
    const fs110 = normalize("FS-110");
    if (!shownCodes.has(fs110) && geResult.fys && !geResult.fys.complete) {
      shownCodes.add(fs110);
      items.unshift({
        code: fs110, display: "FS-110 First Year Seminar", category: "essential",
        done: allTaken.has(fs110), pct: null, trajSem: null,
      });
    }
  }

  // Required courses from programs placed by trajectory semester
  for (const prog of selectedProgs) {
    for (const sec of (prog.sections || [])) {
      if (sec.type === "all") {
        for (const item of (sec.items || [])) {
          const codes = (item.codes || []).map(normalize);
          const primaryCode = codes.find(c => !isAuxiliary(c)) || codes[0];
          if (!primaryCode || shownCodes.has(primaryCode)) continue;
          const traj = majorCode ? trajectoryInfo(majorCode, primaryCode) : null;
          let targetSem = traj && traj.sem ? traj.sem : 8;
          // Adjust for term compatibility
          const off = OFFERING_TERM[primaryCode];
          if (off && off !== "both") {
            while (targetSem <= 8 && semesterTerm(targetSem) !== off) targetSem++;
            if (targetSem > 8) targetSem = traj && traj.sem ? traj.sem : 8;
          }
          if (targetSem !== semNum) continue;
          shownCodes.add(primaryCode);
          const done = allTaken.has(primaryCode);
          items.push({
            code: primaryCode,
            display: `${primaryCode} ${item.title || ""}`.trim(),
            category: "required", done,
            pct: traj ? traj.pct : null, trajSem: traj ? traj.sem : null,
          });
        }
      }
    }
  }

  // Trajectory electives (primarily semesters 5-8, capped at 3)
  if (majorCode && semNum >= 3) {
    const maj = DATA.trajectory[majorCode] || {};
    let elecCount = 0;
    const rows = [];
    for (const [code, info] of Object.entries(maj)) {
      if (shownCodes.has(code) || allTaken.has(code)) continue;
      if ((info.tier === "elective" || info.tier === "common") && info.pct >= 0.15) {
        const off = OFFERING_TERM[code];
        if (off && off !== "both" && off !== term) continue;
        if (info.sem === semNum) rows.push([code, info]);
      }
    }
    rows.sort((a, b) => b[1].pct - a[1].pct);
    for (const [code, info] of rows.slice(0, 3)) {
      if (elecCount >= 3) break;
      shownCodes.add(code);
      items.push({
        code, display: code, category: "elective", done: false,
        pct: info.pct, trajSem: info.sem,
      });
      elecCount++;
    }
  }

  return items;
}

function buildPlanHints(semNum, allTaken, geResult, completed) {
  if (completed) return [];
  const hints = [];

  // FYS
  if (semNum <= 2 && geResult.fys && !geResult.fys.complete)
    hints.push("need First Year Seminar");

  // Divisional GE
  const divNames = {
    fine_arts: "Fine Arts", humanities: "Humanities",
    nat_sci_math: "Nat Sci/Math", social_sciences: "Social Sciences",
  };
  for (const [key, label] of Object.entries(divNames)) {
    if (geResult[key] && !geResult[key].complete) hints.push(`need ${label} GE`);
  }

  // Lab science
  if (geResult.lab_science && !geResult.lab_science.complete)
    hints.push("need Lab Science");

  // WE (relevant in later semesters)
  if (semNum >= 2 && geResult.we && !geResult.we.complete) {
    const remaining = geResult.we.required - geResult.we.courses.length;
    if (remaining > 0) hints.push(`need WE course (${remaining} remaining)`);
  }

  // DAC
  if (semNum >= 2 && geResult.dac && !geResult.dac.complete) {
    const remaining = geResult.dac.required - geResult.dac.courses.length;
    if (remaining > 0) hints.push(`need DAC course (${remaining} remaining)`);
  }

  // Practicum
  if (semNum >= 5 && geResult.practicum && !geResult.practicum.complete)
    hints.push("need Practicum");

  return hints;
}

function findMajorCode(programs) {
  for (const p of programs) {
    if (p.program_type === "major" && p.major_code) return p.major_code;
  }
  return "";
}

function findF2YEntries(programs, activePathways) {
  const f2y = DATA.first_two_years || { entries: [] };
  const entries = f2y.entries || f2y;
  if (!Array.isArray(entries)) return [];
  const activePwSet = new Set(activePathways || []);
  const result = [];

  for (const prog of programs) {
    const majorCode = prog.major_code || "";
    const progId = prog.id || "";

    // Find all F2Y entries matching this program
    const matching = entries.filter(entry => {
      const matchCodes = entry.match_major_codes || [];
      const matchIds = entry.match_program_ids || [];
      return matchCodes.includes(majorCode) || matchIds.includes(progId);
    });

    // Select the right variant based on conditions
    let chosen = null;

    // First: look for a conditional entry whose conditions are met
    for (const entry of matching) {
      const cond = entry.conditions;
      if (!cond) continue;
      if (cond.intake_only) continue; // wizard-only, skip in Plan tab
      if (cond.pathways && cond.pathways.some(pw => activePwSet.has(pw))) {
        chosen = entry;
        break;
      }
    }

    // Fallback: use the default entry
    if (!chosen) {
      chosen = matching.find(e => e.default === true)
            || matching.find(e => !e.conditions);
    }

    if (chosen) result.push(chosen);
  }
  return result;
}

// ─── .adv file format ────────────────────────────────────────────────────────

function generateAdv() {
  const name = document.getElementById("student-name").value.trim();
  const id = document.getElementById("student-id").value.trim();
  const year = document.getElementById("student-year").value;
  const now = new Date();
  const dateStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")} ${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}`;

  const lines = [
    "# Coe College Academic Advising Student File",
    `# Generated: ${dateStr}`,
    "",
    `NAME: ${name}`,
    `ID: ${id}`,
    `YEAR: ${year}`,
  ];

  for (let i = 1; i <= 3; i++) {
    const sel = document.getElementById(`major${i}`);
    lines.push(`MAJOR${i}: ${sel ? sel.value : ""}`);
  }
  for (let i = 1; i <= 2; i++) {
    const sel = document.getElementById(`minor${i}`);
    lines.push(`MINOR${i}: ${sel ? sel.value : ""}`);
  }

  const activePw = [];
  document.querySelectorAll(".pw-check input:checked").forEach(cb => activePw.push(cb.value));
  lines.push(`PATHWAYS: ${activePw.join(", ")}`);
  lines.push(`TRANSFER_WE: ${document.getElementById("transfer-we").value}`);
  lines.push("");

  // Other requirements
  document.querySelectorAll("#other-reqs .other-req-item").forEach(el => {
    const id = el.dataset.reqId;
    const checked = el.querySelector("input[type=checkbox]")?.checked || false;
    const note = el.querySelector(".other-req-note")?.value?.trim() || "";
    if (checked || note) {
      lines.push(`OTHER: ${id}, ${checked ? "completed" : "incomplete"}, ${note}`);
    }
  });

  // Professional requirements
  document.querySelectorAll("#prof-reqs .other-req-item").forEach(el => {
    const id = el.dataset.reqId;
    const checked = el.querySelector("input[type=checkbox]")?.checked || false;
    const note = el.querySelector(".other-req-note")?.value?.trim() || "";
    if (checked || note) {
      lines.push(`PROF: ${id}, ${checked ? "completed" : "incomplete"}, ${note}`);
    }
  });
  const schoolCourses = (document.getElementById("school-courses")?.value || "").trim();
  if (schoolCourses) lines.push(`SCHOOL_COURSES: ${schoolCourses.replace(/\n/g, ", ")}`);
  lines.push("");

  document.querySelectorAll("#plan-semesters .plan-semester").forEach(semEl => {
    const label = semEl.querySelector(".plan-sem-label").textContent.trim();
    const text = semEl.querySelector(".sem-courses").value.trim();
    if (!text) return;
    const done = semEl.querySelector(".sem-status input").checked;
    const status = done ? "completed" : "planned";
    lines.push(`SEMESTER: ${label}`);
    for (const code of text.split(/\n/)) {
      const c = code.trim();
      if (c) lines.push(`COURSE: ${c}, ${status}`);
    }
    lines.push("");
  });

  return lines.join("\n");
}

function downloadAdv() {
  const name = document.getElementById("student-name").value.trim() || "student";
  const now = new Date();
  const ds = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,"0")}${String(now.getDate()).padStart(2,"0")}`;
  const fname = `student_${name.replace(/\s+/g, "_")}_${ds}.adv`;
  const blob = new Blob([generateAdv()], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = fname;
  a.click();
  URL.revokeObjectURL(a.href);
}

function loadAdv(text) {
  const fields = {
    NAME: "", ID: "", YEAR: "", PATHWAYS: "", TRANSFER_WE: "",
    MAJOR1: "", MAJOR2: "", MAJOR3: "", MINOR1: "", MINOR2: "",
  };
  const semesters = [];
  const otherReqs = [];
  const profReqs = [];
  let schoolCourses = "";
  let currentSem = null;
  const oldCourses = [];
  let inOldCourses = false;

  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s || s.startsWith("#")) continue;

    if (s.startsWith("OTHER:")) {
      const parts = s.slice(6).split(",").map(x => x.trim());
      const id = parts[0] || "";
      const status = parts[1] || "incomplete";
      const note = parts.slice(2).join(",").trim();
      if (id) otherReqs.push({ id, completed: status === "completed", note });
      continue;
    }

    if (s.startsWith("PROF:")) {
      const parts = s.slice(5).split(",").map(x => x.trim());
      const id = parts[0] || "";
      const status = parts[1] || "incomplete";
      const note = parts.slice(2).join(",").trim();
      if (id) profReqs.push({ id, completed: status === "completed", note });
      continue;
    }

    if (s.startsWith("SCHOOL_COURSES:")) {
      schoolCourses = s.slice(15).trim();
      continue;
    }

    if (s === "COURSES:") { inOldCourses = true; continue; }

    if (s.startsWith("SEMESTER:")) {
      inOldCourses = false;
      currentSem = { label: s.slice(9).trim(), courses: [], hasCompleted: false, hasPlanned: false };
      semesters.push(currentSem);
      continue;
    }

    if (s.startsWith("COURSE:") && currentSem) {
      const parts = s.slice(7).trim().split(",");
      const code = (parts[0] || "").trim();
      const status = (parts[1] || "").trim().toLowerCase();
      if (code) {
        currentSem.courses.push(code);
        if (status === "planned") currentSem.hasPlanned = true;
        else currentSem.hasCompleted = true;
      }
      continue;
    }

    if (inOldCourses) { oldCourses.push(s); continue; }

    if (s.startsWith("PROGRAMS:")) {
      const pids = s.slice(9).split(",").map(x => x.trim()).filter(Boolean);
      let mi = 0, ni = 0;
      for (const pid of pids) {
        const prog = DATA.programs[pid];
        if (!prog) continue;
        const pt = prog.program_type || "";
        if (["major","collateral","certificate"].includes(pt) && mi < 3) {
          mi++; fields[`MAJOR${mi}`] = pid;
        } else if (pt === "minor" && ni < 2) {
          ni++; fields[`MINOR${ni}`] = pid;
        }
      }
      continue;
    }

    for (const key of Object.keys(fields)) {
      if (s.startsWith(key + ":")) {
        fields[key] = s.slice(key.length + 1).trim();
        break;
      }
    }
  }

  document.getElementById("student-name").value = fields.NAME;
  document.getElementById("student-id").value = fields.ID;
  const yearSel = document.getElementById("student-year");
  if ([...yearSel.options].some(o => o.value === fields.YEAR)) yearSel.value = fields.YEAR;

  for (let i = 1; i <= 3; i++) {
    const sel = document.getElementById(`major${i}`);
    if (sel) sel.value = fields[`MAJOR${i}`] || "";
  }
  for (let i = 1; i <= 2; i++) {
    const sel = document.getElementById(`minor${i}`);
    if (sel) sel.value = fields[`MINOR${i}`] || "";
  }

  const pws = fields.PATHWAYS.split(",").map(x => x.trim()).filter(Boolean);
  // Pathway checkboxes are restored after updatePathways() below

  let weVal = fields.TRANSFER_WE;
  if (weVal === "8 credits \u2014 max (3 WE)") weVal = "8\u201315 credits (3 WE)";
  const weSel = document.getElementById("transfer-we");
  if ([...weSel.options].some(o => o.value === weVal)) weSel.value = weVal;

  // Build semester grid in Plan tab
  const semContainer = document.getElementById("plan-semesters");
  semContainer.innerHTML = "";
  const semData = semesters.length > 0 ? semesters
    : oldCourses.length > 0 ? [{ label: "Semester 1", courses: oldCourses }]
    : [];

  if (semData.length === 0) {
    createDefaultPlanSemesters();
  } else {
    // Map labels to semester numbers for term-awareness
    const labelToNum = {};
    for (const [num, lbl] of Object.entries(PLAN_SEM_LABELS)) labelToNum[lbl] = parseInt(num);
    for (let idx = 0; idx < semData.length; idx++) {
      const sd = semData[idx];
      const completed = sd.hasCompleted && !sd.hasPlanned;
      // Detect semester number from old "Semester N" or new PLAN_SEM_LABELS style
      const semMatch = sd.label.match(/^Semester\s+(\d+)$/i);
      let semNum = semMatch ? parseInt(semMatch[1]) : (labelToNum[sd.label] || null);
      const displayLabel = semNum && PLAN_SEM_LABELS[semNum] ? PLAN_SEM_LABELS[semNum] : sd.label;
      addPlanSemester(displayLabel, sd.courses.join("\n"), completed, semNum);
    }
  }
  // Rebuild pathways for the loaded majors, then restore checked state
  updatePathways();
  document.querySelectorAll(".pw-check input").forEach(cb => {
    cb.checked = pws.includes(cb.value);
  });

  // Rebuild other reqs for loaded programs, then restore state
  buildOtherReqs();
  for (const req of otherReqs) {
    const el = document.querySelector(`.other-req-item[data-req-id="${req.id}"]`);
    if (!el) continue;
    const cb = el.querySelector("input[type=checkbox]");
    if (cb) { cb.checked = req.completed; el.classList.toggle("done", req.completed); }
    const noteInput = el.querySelector(".other-req-note");
    if (noteInput) noteInput.value = req.note;
  }

  // Rebuild professional reqs for loaded pathways, then restore state
  buildProfReqs();
  for (const req of profReqs) {
    const el = document.querySelector(`#prof-reqs .other-req-item[data-req-id="${req.id}"]`);
    if (!el) continue;
    const cb = el.querySelector("input[type=checkbox]");
    if (cb) { cb.checked = req.completed; el.classList.toggle("done", req.completed); }
    const noteInput = el.querySelector(".other-req-note");
    if (noteInput) noteInput.value = req.note;
  }
  const schoolTA = document.getElementById("school-courses");
  if (schoolTA && schoolCourses) schoolTA.value = schoolCourses.replace(/,\s*/g, "\n");

  runCheck();
}

// ─── UI rendering ────────────────────────────────────────────────────────────

let currentTab = "ge";

function showTab(tab) {
  currentTab = tab;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("active", p.id === "tab-" + tab));
}

function gatherData() {
  const progIds = [];
  for (let i = 1; i <= 3; i++) {
    const v = document.getElementById(`major${i}`).value;
    if (v) progIds.push(v);
  }
  for (let i = 1; i <= 2; i++) {
    const v = document.getElementById(`minor${i}`).value;
    if (v) progIds.push(v);
  }

  const activePw = [];
  document.querySelectorAll(".pw-check input:checked").forEach(cb => activePw.push(cb.value));

  const allCourses = new Set();
  const semesters = [];
  document.querySelectorAll("#plan-semesters .plan-semester").forEach((semEl, i) => {
    const ta = semEl.querySelector(".sem-courses");
    const courses = parseCourses(ta ? ta.value : "");
    const completed = semEl.querySelector(".sem-status input")?.checked || false;
    const label = (semEl.querySelector(".plan-sem-label")?.textContent || "").trim();
    const semNum = parseInt(semEl.dataset.semNum) || null;
    for (const c of courses) allCourses.add(c);
    semesters.push({ label, semNum, courses, completed });
  });

  // Include school-specific courses from professional requirements
  const schoolTA = document.getElementById("school-courses");
  if (schoolTA) {
    for (const c of parseCourses(schoolTA.value)) allCourses.add(c);
  }

  return { progIds, activePw, taken: allCourses, semesters };
}

function runCheck() {
  buildProfReqs();
  const { progIds, activePw, taken } = gatherData();
  const overrides = {};
  for (const [k, v] of Object.entries((DATA.course_credits || {}).overrides || {}))
    overrides[normalize(k)] = v;

  const dacSet = new Set(DATA.dac.courses || DATA.dac || []);
  const weSet = new Set(DATA.we.courses || DATA.we || []);

  // WE adjustment
  const transferWe = document.getElementById("transfer-we").value;
  let weRequired = 5;
  if (transferWe.includes("16+")) weRequired = 2;
  else if (transferWe.includes("8")) weRequired = 3;

  const geResult = checkGE(DATA.ge, taken, dacSet, weSet);
  geResult.we.required = weRequired;
  geResult.we.complete = geResult.we.courses.length >= weRequired;
  geResult.we.label = `Writing Emphasis (${weRequired} courses)`;

  const selectedProgs = progIds.map(id => DATA.programs[id]).filter(Boolean);
  const progResults = selectedProgs.map(prog => checkProgram(prog, taken));

  const pwResults = activePw.map(id => DATA.pathways[id]).filter(Boolean)
    .map(pw => checkProgram(pw, taken));

  const credits = totalCredits(taken, overrides);

  // Render — always show results since Plan tab has editable content
  const resultsEl = document.getElementById("results");
  const emptyEl = document.getElementById("results-empty");
  emptyEl.style.display = "none";
  resultsEl.style.display = "block";

  document.getElementById("summary-bar").textContent =
    `${taken.size} courses \u00b7 ${credits.toFixed(1)} credits \u00b7 ${progResults.length} program(s)`;

  renderGE(geResult);
  renderPrograms(progResults, pwResults);
  renderPlan(selectedProgs, taken, geResult, activePw, overrides);
}

function renderGE(ge) {
  const el = document.getElementById("ge-content");
  let html = "";
  const order = ["fine_arts","humanities","nat_sci_math","lab_science","social_sciences",
                 "fys","we","dac","practicum"];
  for (const key of order) {
    const r = ge[key];
    if (!r) continue;
    const cls = r.complete ? "done" : "todo";
    const icon = r.complete ? "\u2713" : "\u2717";
    let courses = "";
    if (r.courses && r.courses.length > 0)
      courses = r.courses.join(", ");
    else if (r.pairs && r.pairs.length > 0)
      courses = r.pairs.map(p => p.join(" + ")).join(", ");
    const countStr = r.courses ? `${r.courses.length}/${r.required}` :
                     r.pairs ? `${r.pairs.length}/${r.required}` : "";
    html += `<div class="req-row ${cls}">
      <span class="req-icon">${icon}</span>
      <span class="req-label">${r.label}</span>
      <span class="req-courses">${courses}${countStr ? " (" + countStr + ")" : ""}</span>
    </div>`;
  }
  el.innerHTML = html;
}

function renderPrograms(progResults, pwResults) {
  const el = document.getElementById("programs-content");
  let html = "";
  for (const pr of [...progResults, ...pwResults]) {
    const prog = pr.program;
    const pct = pr.total > 0 ? Math.round(pr.complete / pr.total * 100) : 0;
    html += `<div class="prog-card open">
      <div class="prog-header" onclick="this.parentElement.classList.toggle('open')">
        <span class="arrow">\u25B6</span>
        <strong>${prog.name || prog.id}</strong>
        <span class="prog-pct">${pr.complete}/${pr.total} (${pct}%)</span>
      </div>
      <div class="prog-body">${renderSections(pr.sections)}</div>
    </div>`;
  }
  if (!html) html = '<div class="empty">Select programs to see requirements</div>';
  el.innerHTML = html;
}

function renderSections(sections) {
  let html = "";
  for (const s of sections) {
    const cls = s.status === COMPLETE ? "done" : s.status === PARTIAL ? "partial"
      : s.status === MANUAL ? "manual" : "todo";
    const icon = s.status === COMPLETE ? "\u2713" : s.status === PARTIAL ? "\u25D1"
      : s.status === MANUAL ? "\u2139" : "\u2717";
    html += `<div class="sec-row ${cls}">
      <span class="req-icon">${icon}</span>
      <span class="sec-label">${s.label || s.id}</span>
      <span class="sec-msg">${s.message || ""}</span>
    </div>`;
    if (s.items) {
      for (const it of s.items) {
        const ic = it.satisfied ? "\u2713" : "\u2717";
        const c = it.satisfied ? "done" : "todo";
        html += `<div class="item-row ${c}">
          <span class="req-icon">${ic}</span>
          <span>${it.title || ""} <span class="req-courses">${(it.codes||[]).join(", ")}</span></span>
        </div>`;
      }
    }
    if (s.options) {
      for (const o of s.options) {
        const ic = o.satisfied ? "\u2713" : "\u2717";
        const c = o.satisfied ? "done" : "todo";
        html += `<div class="item-row ${c}">
          <span class="req-icon">${ic}</span>
          <span>${o.title || ""} <span class="req-courses">${(o.codes||[]).join(", ")}</span></span>
        </div>`;
      }
    }
  }
  return html;
}

function renderPlan(selectedProgs, taken, geResult, activePathways, overrides) {
  const semEls = document.querySelectorAll("#plan-semesters .plan-semester");
  if (semEls.length === 0) return;

  const majorCode = findMajorCode(selectedProgs);
  const shownCodes = new Set();

  semEls.forEach(semEl => {
    const semNum = parseInt(semEl.dataset.semNum) || null;
    const completed = semEl.querySelector(".sem-status input")?.checked || false;
    const ta = semEl.querySelector(".sem-courses");
    const enteredCourses = parseCourses(ta ? ta.value : "");

    // Make textarea readonly when completed
    if (ta) ta.readOnly = completed;

    const hintsEl = semEl.querySelector(".plan-hints");
    const suggestEl = semEl.querySelector(".plan-suggestions");
    if (!hintsEl || !suggestEl) return;

    // --- Hints ---
    let hintsHTML = "";
    if (!completed && semNum) {
      // Term conflict warnings for entered courses
      const warnings = [];
      for (const code of enteredCourses) {
        const conflict = checkTermConflict(code, semNum);
        if (conflict) warnings.push(`<div class="term-warning">\u26A0 ${conflict}</div>`);
      }
      if (warnings.length > 0) hintsHTML += warnings.join("");

      // GE hints
      const hints = buildPlanHints(semNum, taken, geResult, completed);
      if (hints.length > 0) {
        hintsHTML += hints.map(h => `<span class="plan-hint-item">${h}</span>`).join("");
      }
    }
    hintsEl.innerHTML = hintsHTML;
    hintsEl.style.display = hintsHTML ? "" : "none";

    // --- Suggestions ---
    let sugHTML = "";
    if (!completed && selectedProgs.length > 0 && semNum) {
      const items = buildSemesterSuggestions(semNum, taken, shownCodes, selectedProgs, geResult, majorCode, activePathways);
      for (const item of items) {
        const cls = item.done ? "done" : "todo";
        const icon = item.done ? "\u2713" : "\u25CB";
        const badge = termBadgeHTML(item.code);
        let hint = "";
        if (item.pct != null) hint = `${Math.round(item.pct * 100)}% of grads`;
        if (item.trajSem) hint += (hint ? " \u00b7 " : "") + `Sem ${item.trajSem}`;
        const catLabel = item.category === "suggested" ? " (suggested)" :
                         item.category === "elective" ? " (elective)" : "";
        sugHTML += `<div class="plan-item ${cls}">
          <span class="icon">${icon}</span>
          <span class="label">${item.display}${catLabel}${badge}</span>
          ${hint ? `<span class="hint">${hint}</span>` : ""}
        </div>`;
      }
    }
    suggestEl.innerHTML = sugHTML;
    suggestEl.style.display = sugHTML ? "" : "none";

    // --- Summary in header ---
    const summaryEl = semEl.querySelector(".plan-sem-summary");
    if (summaryEl) {
      const count = enteredCourses.length;
      if (count > 0) {
        let credits = 0;
        for (const c of enteredCourses) credits += creditOf(c, overrides);
        const warn = semNum && (credits < 3 || credits > 5);
        summaryEl.textContent = `${count} course${count !== 1 ? "s" : ""} \u00b7 ${credits % 1 === 0 ? credits : credits.toFixed(1)} cr`;
        summaryEl.classList.toggle("sem-credit-warn", warn);
      } else {
        summaryEl.textContent = "";
        summaryEl.classList.remove("sem-credit-warn");
      }
    }
  });
}

// ─── Intake wizard ───────────────────────────────────────────────────────────

function showIntakeWizard() {
  const majorId = document.getElementById("major1").value;
  if (!majorId) { alert("Select a major first."); return; }

  const intake = DATA.intake[majorId] || DATA.intake["_default"];
  if (!intake) { alert("No intake questions available."); return; }

  const modal = document.getElementById("wizard-modal");
  const body = document.getElementById("wizard-body");

  let html = "";
  if (intake.intro) html += `<p>${intake.intro}</p>`;
  for (const q of (intake.questions || [])) {
    html += `<div class="question">
      <div>${q.text}</div>
      <label><input type="radio" name="wiz_${q.id}" value="yes"> Yes</label>
      <label><input type="radio" name="wiz_${q.id}" value="no" checked> No</label>
    </div>`;
  }
  body.innerHTML = html;
  modal.classList.add("visible");
  modal.dataset.intakeId = intake.program_id;
}

function submitWizard() {
  const modal = document.getElementById("wizard-modal");
  const intakeId = modal.dataset.intakeId;
  const intake = DATA.intake[intakeId] || DATA.intake["_default"];
  if (!intake) return;

  const answers = {};
  for (const q of (intake.questions || [])) {
    const sel = document.querySelector(`input[name="wiz_${q.id}"]:checked`);
    answers[q.id] = sel ? sel.value === "yes" : false;
  }

  let matchedRoute = null;
  for (const route of (intake.routes || [])) {
    const when = route.when || {};
    let match = true;
    for (const [k, v] of Object.entries(when)) {
      if (answers[k] !== v) { match = false; break; }
    }
    if (match) { matchedRoute = route; break; }
  }

  modal.classList.remove("visible");

  if (!matchedRoute) return;

  // Apply route
  if (matchedRoute.major && DATA.programs[matchedRoute.major]) {
    document.getElementById("major1").value = matchedRoute.major;
  }
  // Rebuild pathways for the new major, then check the route's pathway
  updatePathways();
  if (matchedRoute.pathway) {
    document.querySelectorAll(".pw-check input").forEach(cb => {
      if (cb.value === matchedRoute.pathway) cb.checked = true;
    });
  }

  // Pre-populate first semester courses
  if (matchedRoute.semester_1 && matchedRoute.semester_1.length > 0) {
    const semContainer = document.getElementById("plan-semesters");
    semContainer.innerHTML = "";
    addPlanSemester(PLAN_SEM_LABELS[1], matchedRoute.semester_1.join("\n"), false, 1);
    for (let i = 2; i <= 8; i++) addPlanSemester(PLAN_SEM_LABELS[i], "", false, i);
  }

  // Show route note
  if (matchedRoute.note) {
    const noteEl = document.getElementById("route-note");
    noteEl.textContent = matchedRoute.note;
    noteEl.style.display = "block";
  }

  runCheck();
}

function closeWizard() {
  document.getElementById("wizard-modal").classList.remove("visible");
}

// ─── Other Requirements ─────────────────────────────────────────────────────

function buildOtherReqs() {
  const container = document.getElementById("other-reqs");

  // Preserve existing state
  const prevState = {};
  container.querySelectorAll(".other-req-item").forEach(el => {
    const id = el.dataset.reqId;
    prevState[id] = {
      checked: el.querySelector("input[type=checkbox]")?.checked || false,
      note: el.querySelector(".other-req-note")?.value || "",
    };
  });

  // Build items list: Practicum (always) + program non_course sections
  const items = [
    { id: "practicum", label: "Practicum" },
  ];

  const selectedProgIds = [];
  for (let i = 1; i <= 3; i++) {
    const v = document.getElementById(`major${i}`).value;
    if (v) selectedProgIds.push(v);
  }
  for (let i = 1; i <= 2; i++) {
    const v = document.getElementById(`minor${i}`).value;
    if (v) selectedProgIds.push(v);
  }

  const seenIds = new Set(["practicum"]);
  for (const pid of selectedProgIds) {
    const prog = DATA.programs[pid];
    if (!prog) continue;
    for (const sec of (prog.sections || [])) {
      if (sec.type !== "non_course") continue;
      const reqId = pid + "_" + (sec.id || sec.label.replace(/\s+/g, "_").toLowerCase().slice(0, 40));
      if (seenIds.has(reqId)) continue;
      seenIds.add(reqId);
      items.push({ id: reqId, label: sec.label, description: sec.description || "" });
    }
  }

  // Render
  container.innerHTML = "";
  for (const item of items) {
    const prev = prevState[item.id] || {};
    const checked = prev.checked ? " checked" : "";
    const note = prev.note || "";
    const doneClass = prev.checked ? " done" : "";
    const title = item.description ? ` title="${item.description.replace(/"/g, '&quot;')}"` : "";
    const div = document.createElement("div");
    div.className = `other-req-item${doneClass}`;
    div.dataset.reqId = item.id;
    div.innerHTML = `<label${title}><input type="checkbox"${checked}> ${item.label}</label>
      <input type="text" class="other-req-note" placeholder="Notes..." value="${note.replace(/"/g, '&quot;')}">`;
    // Toggle done styling on checkbox change
    div.querySelector("input[type=checkbox]").addEventListener("change", function() {
      div.classList.toggle("done", this.checked);
    });
    container.appendChild(div);
  }
}

// ─── Professional Requirements ──────────────────────────────────────────────

function buildProfReqs() {
  const container = document.getElementById("prof-reqs");
  const section = document.getElementById("prof-reqs-section");

  // Get active pathways
  const activePwIds = [];
  document.querySelectorAll(".pw-check input:checked").forEach(cb => activePwIds.push(cb.value));

  if (activePwIds.length === 0) {
    section.style.display = "none";
    container.innerHTML = "";
    return;
  }

  section.style.display = "";

  // Preserve existing state
  const prevState = {};
  container.querySelectorAll(".other-req-item").forEach(el => {
    const id = el.dataset.reqId;
    prevState[id] = {
      checked: el.querySelector("input[type=checkbox]")?.checked || false,
      note: el.querySelector(".other-req-note")?.value || "",
    };
  });

  // Collect non_course sections from active pathways
  const items = [];
  const seenIds = new Set();
  for (const pwId of activePwIds) {
    const pw = DATA.pathways[pwId];
    if (!pw) continue;
    for (const sec of (pw.sections || [])) {
      if (sec.type !== "non_course") continue;
      const reqId = "prof_" + pwId + "_" + (sec.id || sec.label.replace(/\s+/g, "_").toLowerCase().slice(0, 40));
      if (seenIds.has(reqId)) continue;
      seenIds.add(reqId);
      items.push({ id: reqId, label: sec.label, description: sec.description || "" });
    }
  }

  container.innerHTML = "";
  for (const item of items) {
    const prev = prevState[item.id] || {};
    const checked = prev.checked ? " checked" : "";
    const note = prev.note || "";
    const doneClass = prev.checked ? " done" : "";
    const title = item.description ? ` title="${item.description.replace(/"/g, '&quot;')}"` : "";
    const div = document.createElement("div");
    div.className = `other-req-item${doneClass}`;
    div.dataset.reqId = item.id;
    div.innerHTML = `<label${title}><input type="checkbox"${checked}> ${item.label}</label>
      <input type="text" class="other-req-note" placeholder="Notes..." value="${note.replace(/"/g, '&quot;')}">`;
    div.querySelector("input[type=checkbox]").addEventListener("change", function() {
      div.classList.toggle("done", this.checked);
    });
    container.appendChild(div);
  }
}

// ─── Pathways ────────────────────────────────────────────────────────────────

function updatePathways() {
  const selectedProgIds = [];
  for (let i = 1; i <= 3; i++) {
    const v = document.getElementById(`major${i}`).value;
    if (v) selectedProgIds.push(v);
  }

  const pwContainer = document.getElementById("pathways");
  // Remember which were checked
  const checked = new Set();
  pwContainer.querySelectorAll("input:checked").forEach(cb => checked.add(cb.value));

  pwContainer.innerHTML = "";
  let count = 0;
  for (const [id, pw] of Object.entries(DATA.pathways || {})) {
    const related = pw.related_programs || [];
    // Only show pathways relevant to selected programs
    if (selectedProgIds.length > 0 && related.length > 0
        && !related.some(rp => selectedProgIds.includes(rp))) continue;
    // Don't show any pathways if no major is selected
    if (selectedProgIds.length === 0) continue;
    const label = document.createElement("label");
    label.className = "pw-check";
    const isChecked = checked.has(id) ? " checked" : "";
    label.innerHTML = `<input type="checkbox" value="${id}"${isChecked}> ${pw.name || id}`;
    pwContainer.appendChild(label);
    count++;
  }

  document.getElementById("pathways-row").style.display = count > 0 ? "" : "none";
}

// ─── Plan semester management ────────────────────────────────────────────────

function addPlanSemester(label, courses, completed, semNum) {
  label = label || `Semester ${document.querySelectorAll("#plan-semesters .plan-semester").length + 1}`;
  courses = courses || "";
  if (completed === undefined) completed = false;
  const container = document.getElementById("plan-semesters");
  const div = document.createElement("div");
  div.className = "plan-semester open";
  if (semNum) div.dataset.semNum = semNum;
  const checkedAttr = completed ? " checked" : "";
  const readonlyAttr = completed ? " readonly" : "";
  div.innerHTML = `<div class="plan-sem-header" onclick="togglePlanSem(event, this)">
    <span class="arrow">\u25B6</span>
    <span class="plan-sem-label">${label}</span>
    <span class="plan-sem-summary"></span>
    <label class="sem-status" onclick="event.stopPropagation()">
      <input type="checkbox"${checkedAttr} onchange="onPlanSemCompleted(this)"> Completed
    </label>
    <button class="small-btn remove-sem" onclick="event.stopPropagation(); this.closest('.plan-semester').remove(); runCheck();" title="Remove">\u00d7</button>
  </div>
  <div class="plan-sem-body">
    <div class="plan-entry-area">
      <textarea class="sem-courses" rows="3" placeholder="One course per line: BIO-145, CHM 121..."${readonlyAttr}>${courses}</textarea>
    </div>
    <div class="plan-hints" style="display:none"></div>
    <div class="plan-suggestions" style="display:none"></div>
  </div>`;
  container.appendChild(div);
  if (courses && completed) div.classList.remove("open");
}

function createDefaultPlanSemesters() {
  const container = document.getElementById("plan-semesters");
  container.innerHTML = "";
  addPlanSemester("Transfer", "", false, null);
  for (let i = 1; i <= 8; i++) addPlanSemester(PLAN_SEM_LABELS[i], "", false, i);
}

function togglePlanSem(e, header) {
  if (e.target.closest(".sem-status") || e.target.closest(".remove-sem")) return;
  header.closest(".plan-semester").classList.toggle("open");
}

function onPlanSemCompleted(checkbox) {
  const semEl = checkbox.closest(".plan-semester");
  const ta = semEl.querySelector(".sem-courses");
  if (checkbox.checked) {
    ta.readOnly = true;
    semEl.classList.remove("open");
  } else {
    ta.readOnly = false;
    semEl.classList.add("open");
  }
  runCheck();
}

// ─── Initialization ──────────────────────────────────────────────────────────

function init() {
  const studentYears = ["First Year", "Sophomore", "Junior", "Senior", "Transfer Student"];
  const yearSel = document.getElementById("student-year");
  for (const y of studentYears) {
    const opt = document.createElement("option");
    opt.value = y; opt.textContent = y;
    yearSel.appendChild(opt);
  }

  // Populate program dropdowns
  const majors = [], minors = [];
  for (const [id, p] of Object.entries(DATA.programs)) {
    const entry = { id, name: p.name, catalog_year: p.catalog_year || "", program_type: p.program_type || "" };
    if (["major", "collateral", "certificate"].includes(p.program_type)) majors.push(entry);
    else if (p.program_type === "minor") minors.push(entry);
  }
  majors.sort((a, b) => a.name.localeCompare(b.name));
  minors.sort((a, b) => a.name.localeCompare(b.name));

  for (let i = 1; i <= 3; i++) {
    const sel = document.getElementById(`major${i}`);
    sel.innerHTML = '<option value="">(none)</option>';
    for (const m of majors) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `${m.name} (${m.catalog_year})`;
      sel.appendChild(opt);
    }
  }
  for (let i = 1; i <= 2; i++) {
    const sel = document.getElementById(`minor${i}`);
    sel.innerHTML = '<option value="">(none)</option>';
    for (const m of minors) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `${m.name} (${m.catalog_year})`;
      sel.appendChild(opt);
    }
  }

  // Pathways are populated dynamically by updatePathways()

  // Transfer WE
  const weSel = document.getElementById("transfer-we");
  const weOpts = ["0 credits (5 WE)", "1\u20137 credits (5 WE)",
                  "8\u201315 credits (3 WE)", "16+ credits (2 WE)"];
  for (const w of weOpts) {
    const opt = document.createElement("option");
    opt.value = w; opt.textContent = w;
    weSel.appendChild(opt);
  }

  // Build offerings index
  buildOfferingsIndex();

  // Default plan semesters
  createDefaultPlanSemesters();

  // Filter pathways and rebuild other reqs when program selection changes
  function onProgramChange() { updatePathways(); buildOtherReqs(); }
  for (let i = 1; i <= 3; i++) {
    document.getElementById(`major${i}`).addEventListener("change", onProgramChange);
  }
  for (let i = 1; i <= 2; i++) {
    document.getElementById(`minor${i}`).addEventListener("change", buildOtherReqs);
  }

  // Initial other reqs
  buildOtherReqs();

  // Auto-check on changes in left panel (programs, pathways, transfer WE)
  document.getElementById("input-panel").addEventListener("change", () => runCheck());
  document.getElementById("input-panel").addEventListener("input", debounce(runCheck, 500));

  // Auto-check on changes in plan semesters (course textareas)
  const planSems = document.getElementById("plan-semesters");
  planSems.addEventListener("input", debounce(runCheck, 500));

  // Tab switching
  document.querySelectorAll(".tab").forEach(t => {
    t.addEventListener("click", () => showTab(t.dataset.tab));
  });

  // File load
  document.getElementById("file-input").addEventListener("change", e => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => loadAdv(reader.result);
    reader.readAsText(file);
    e.target.value = "";
  });

  // Show results panel and Plan tab immediately
  showTab("plan");
  runCheck();
}

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

document.addEventListener("DOMContentLoaded", init);
