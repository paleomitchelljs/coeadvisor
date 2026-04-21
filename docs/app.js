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
    // Hard floor: no course below this level may count. Distinct from min_level,
    // which is a threshold used with min_level_count. Back-compat: if min_level
    // is set and min_level_count implies all-must-be-above, treat min_level as the floor.
    let floorLvl = c.floor_level || 0;
    if (!floorLvl && minLvl && (!minCnt || minCnt >= n)) floorLvl = minLvl;
    const matching = [...taken].filter(x =>
      !isAuxiliary(x) && (!pfxs.size || pfxs.has(prefixOf(x))) && !excl.has(x)
      && (!floorLvl || levelOf(x) >= floorLvl));
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

function checkGE(ge, taken, dac, we, prxCourses) {
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
    we.has(c) || c.endsWith("W") || c.endsWith("WE")
    || prefixOf(c) === "FYS" || prefixOf(c) === "FS").sort();
  const dacFound = [...taken].filter(c => dac.has(c) && !isAuxiliary(c)).sort();
  const fysFound = [...taken].filter(c =>
    prefixOf(c) === "FYS" || ["FS-110","FS-111","FS-112"].includes(c));
  const prxFound = [...taken].filter(c => prefixOf(c) === "PRX" || (prxCourses && prxCourses.has(c)));

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


function buildSemesterSuggestions(semNum, allTaken, shownCodes, selectedProgs, geResult, majorCode, activePathways) {
  const items = [];
  const term = semesterTerm(semNum);

  // Advice plan courses (all 8 semesters)
  {
    const advicePlans = findAdvicePlan(selectedProgs, activePathways);
    for (const entry of advicePlans) {
      const semData = (entry.semesters || {})[String(semNum)];
      if (!semData) continue;
      for (const cat of ["essential", "suggested"]) {
        for (const item of (semData[cat] || [])) {
          const code = normalize(item);
          if (!/^[A-Z]+-\d+[A-Z]?$/.test(code)) continue;
          if (shownCodes.has(code)) continue;
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

function findAdvicePlan(programs, activePathways) {
  // Find the best advice plan for the selected programs and active pathways.
  // Returns an object with the same shape as old F2Y entries (semesters with
  // essential/suggested arrays) so downstream code works unchanged.
  const advice = DATA.advice || {};
  const activePwSet = new Set(activePathways || []);
  const result = [];

  for (const prog of programs) {
    const majorCode = prog.major_code || "";
    const progId = prog.id || "";

    // Find matching advice entry (by match_programs or major_code)
    let adviceEntry = null;
    for (const [, entry] of Object.entries(advice)) {
      const matchProgs = entry.match_programs || [];
      if (matchProgs.includes(progId)) { adviceEntry = entry; break; }
    }
    if (!adviceEntry) {
      for (const [, entry] of Object.entries(advice)) {
        if (entry.major_code === majorCode) { adviceEntry = entry; break; }
      }
    }
    if (!adviceEntry) continue;

    const plans = adviceEntry.plans || [];
    let chosen = null;

    // Look for a conditional plan whose conditions are met
    for (const plan of plans) {
      const cond = plan.conditions;
      if (!cond) continue;
      if (cond.intake_only) continue;
      if (cond.pathways && cond.pathways.some(pw => activePwSet.has(pw))) {
        chosen = plan; break;
      }
    }

    // Fallback: default plan
    if (!chosen) {
      chosen = plans.find(p => p.default === true) || plans[0];
    }

    if (chosen) {
      // Build F2Y-compatible shape: semesters keyed y1_fall..y2_spring
      // plus new numeric keys for semesters 5-8
      const semMap = { 1: "y1_fall", 2: "y1_spring", 3: "y2_fall", 4: "y2_spring" };
      const semesters = {};
      const planSems = chosen.semesters || {};
      for (let i = 1; i <= 8; i++) {
        const semData = planSems[String(i)] || { essential: [], suggested: [] };
        if (i <= 4) semesters[semMap[i]] = semData;
        semesters[String(i)] = semData;
      }
      result.push({
        semesters,
        label: chosen.label || "",
        notes: chosen.general_notes || "",
        match_major_codes: [majorCode],
      });
    }
  }
  return result;
}

// Legacy alias — old code references findF2YEntries
function findF2YEntries(programs, activePathways) {
  return findAdvicePlan(programs, activePathways);
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
    `CATALOG_YEAR: ${document.getElementById("catalog-year").value}`,
  ];

  const majorSels = document.querySelectorAll("#major-slots .major-select");
  for (let i = 0; i < 3; i++) {
    lines.push(`MAJOR${i+1}: ${majorSels[i] ? majorSels[i].value : ""}`);
    const concSel = majorSels[i]?.closest("label")?.querySelector(".conc-select");
    lines.push(`MAJOR${i+1}_CONC: ${concSel ? concSel.value : ""}`);
  }
  const minorSels = document.querySelectorAll("#minor-slots .minor-select");
  for (let i = 0; i < 2; i++) {
    lines.push(`MINOR${i+1}: ${minorSels[i] ? minorSels[i].value : ""}`);
    const concSel = minorSels[i]?.closest("label")?.querySelector(".conc-select");
    lines.push(`MINOR${i+1}_CONC: ${concSel ? concSel.value : ""}`);
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

  // Advisor notes
  document.querySelectorAll("#advisor-notes .advisor-note").forEach(noteEl => {
    const date = noteEl.querySelector(".note-date").value;
    const text = noteEl.querySelector(".note-text").value.trim();
    if (date || text) {
      lines.push(`NOTE_START: ${date}`);
      for (const nl of text.split("\n")) lines.push(nl);
      lines.push("NOTE_END");
      lines.push("");
    }
  });

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
    NAME: "", ID: "", YEAR: "", CATALOG_YEAR: "", PATHWAYS: "", TRANSFER_WE: "",
    MAJOR1_CONC: "", MAJOR2_CONC: "", MAJOR3_CONC: "",
    MINOR1_CONC: "", MINOR2_CONC: "",
    MAJOR1: "", MAJOR2: "", MAJOR3: "", MINOR1: "", MINOR2: "",
  };
  const semesters = [];
  const otherReqs = [];
  const profReqs = [];
  const advisorNotes = [];
  let schoolCourses = "";
  let currentSem = null;
  let currentNote = null;
  const oldCourses = [];
  let inOldCourses = false;

  for (const line of text.split("\n")) {
    const s = line.trim();

    // Multi-line note content (must be checked before blank-line skip)
    if (currentNote !== null) {
      if (s === "NOTE_END") { currentNote = null; continue; }
      currentNote.lines.push(line);
      continue;
    }

    if (!s || s.startsWith("#")) continue;

    if (s.startsWith("NOTE_START:")) {
      currentNote = { date: s.slice(11).trim(), lines: [] };
      advisorNotes.push(currentNote);
      continue;
    }

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
      const parts = s.slice(7).trim().split(",").map(x => x.trim()).filter(Boolean);
      const lastPart = (parts[parts.length - 1] || "").toLowerCase();
      let status = "";
      if (lastPart === "completed" || lastPart === "planned") {
        status = lastPart;
        parts.pop();
      }
      for (const code of parts) {
        if (code) currentSem.courses.push(code);
      }
      if (status === "planned") currentSem.hasPlanned = true;
      else if (parts.length > 0) currentSem.hasCompleted = true;
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

    const sortedKeys = Object.keys(fields).sort((a, b) => b.length - a.length);
    for (const key of sortedKeys) {
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

  // Restore catalog year (infer from programs if not saved)
  const catYearSel = document.getElementById("catalog-year");
  let loadedCatYear = fields.CATALOG_YEAR;
  if (!loadedCatYear) {
    const firstProgId = [fields.MAJOR1, fields.MAJOR2, fields.MAJOR3, fields.MINOR1, fields.MINOR2].find(Boolean);
    if (firstProgId && DATA.programs[firstProgId])
      loadedCatYear = DATA.programs[firstProgId].catalog_year || "";
  }
  if (loadedCatYear && [...catYearSel.options].some(o => o.value === loadedCatYear))
    catYearSel.value = loadedCatYear;

  // Rebuild major/minor slots to match loaded data
  const majorContainer = document.getElementById("major-slots");
  majorContainer.innerHTML = "";
  const minorContainer = document.getElementById("minor-slots");
  minorContainer.innerHTML = "";

  // Create major slots: always at least 1, add extras for non-empty values
  const majorVals = [fields.MAJOR1, fields.MAJOR2, fields.MAJOR3].filter(Boolean);
  const majorCount = Math.max(1, majorVals.length);
  for (let i = 0; i < majorCount; i++) {
    if (i === 0) {
      const label = document.createElement("label");
      const sel = document.createElement("select");
      sel.className = "major-select";
      populateMajorSelect(sel);
      sel.value = majorVals[0] || "";
      label.appendChild(sel);
      majorContainer.appendChild(label);
    } else {
      addMajorSlot();
      const sels = majorContainer.querySelectorAll(".major-select");
      sels[i].value = majorVals[i] || "";
    }
  }
  document.querySelector("#major-group .prog-add-btn").style.display =
    majorContainer.querySelectorAll(".major-select").length >= 3 ? "none" : "";

  // Create minor slots: always at least 1, add extras for non-empty values
  const minorVals = [fields.MINOR1, fields.MINOR2].filter(Boolean);
  const minorCount = Math.max(1, minorVals.length);
  for (let i = 0; i < minorCount; i++) {
    if (i === 0) {
      const label = document.createElement("label");
      const sel = document.createElement("select");
      sel.className = "minor-select";
      populateMinorSelect(sel);
      sel.value = minorVals[0] || "";
      label.appendChild(sel);
      minorContainer.appendChild(label);
    } else {
      addMinorSlot();
      const sels = minorContainer.querySelectorAll(".minor-select");
      sels[i].value = minorVals[i] || "";
    }
  }
  document.querySelector("#minor-group .prog-add-btn").style.display =
    minorContainer.querySelectorAll(".minor-select").length >= 2 ? "none" : "";

  // Restore concentration dropdowns and selections
  updateConcentrations();
  const majorConcVals = [fields.MAJOR1_CONC, fields.MAJOR2_CONC, fields.MAJOR3_CONC];
  majorContainer.querySelectorAll(".major-select").forEach((sel, i) => {
    if (majorConcVals[i]) {
      const concSel = sel.closest("label")?.querySelector(".conc-select");
      if (concSel && [...concSel.options].some(o => o.value === majorConcVals[i]))
        concSel.value = majorConcVals[i];
    }
  });
  const minorConcVals = [fields.MINOR1_CONC, fields.MINOR2_CONC];
  minorContainer.querySelectorAll(".minor-select").forEach((sel, i) => {
    if (minorConcVals[i]) {
      const concSel = sel.closest("label")?.querySelector(".conc-select");
      if (concSel && [...concSel.options].some(o => o.value === minorConcVals[i]))
        concSel.value = minorConcVals[i];
    }
  });

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

  // Restore advisor notes
  const notesContainer = document.getElementById("advisor-notes");
  notesContainer.innerHTML = "";
  for (const note of advisorNotes) {
    addAdvisorNote(note.date, note.lines.join("\n").trim());
  }

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
  document.querySelectorAll("#major-slots .major-select").forEach(sel => {
    if (sel.value) progIds.push(sel.value);
  });
  document.querySelectorAll("#minor-slots .minor-select").forEach(sel => {
    if (sel.value) progIds.push(sel.value);
  });

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
  // Also include courses marked WE in the catalog
  if (DATA.catalog && DATA.catalog.prefixes) {
    for (const pfx of Object.values(DATA.catalog.prefixes)) {
      for (const [code, info] of Object.entries(pfx.courses || {})) {
        if (info.we) weSet.add(code);
      }
    }
  }

  // WE adjustment
  const transferWe = document.getElementById("transfer-we").value;
  let weRequired = 5;
  if (transferWe.includes("16+")) weRequired = 2;
  else if (transferWe.includes("8")) weRequired = 3;

  const prxSet = new Set((DATA.practicum || {}).all_courses || []);
  const geResult = checkGE(DATA.ge, taken, dacSet, weSet, prxSet);
  geResult.we.required = weRequired;
  geResult.we.complete = geResult.we.courses.length >= weRequired;
  geResult.we.label = `Writing Emphasis (${weRequired} courses)`;

  // Practicum checkbox in Other Requirements overrides GE practicum
  const prxCb = document.querySelector('#other-reqs .other-req-item[data-req-id="practicum"] input[type=checkbox]');
  if (prxCb && prxCb.checked) geResult.practicum.complete = true;

  const selectedProgs = progIds.map(id => DATA.programs[id]).filter(Boolean);
  const progResults = selectedProgs.map(prog => {
    const result = checkProgram(prog, taken);
    const concId = getSelectedConcentrationForProgram(prog.id);
    if (concId && prog.concentrations) {
      const conc = prog.concentrations.find(c => c.id === concId);
      if (conc) {
        const concSections = (conc.sections || []).map(s => checkSection(s, taken));
        const countable = concSections.filter(s => s.status !== MANUAL);
        result.concentration = {
          name: conc.name, note: conc.note || "",
          sections: concSections,
          total: countable.length,
          complete: countable.filter(s => s.status === COMPLETE).length
        };
      }
    }
    return result;
  });

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
      <div class="prog-body">${renderSections(pr.sections)}${renderConcentration(pr, prog)}</div>
    </div>`;
  }
  if (!html) html = '<div class="empty">Select programs to see requirements</div>';
  el.innerHTML = html;
}

function renderConcentration(pr, prog) {
  if (pr.concentration) {
    const c = pr.concentration;
    const cPct = c.total > 0 ? Math.round(c.complete / c.total * 100) : 0;
    return `<div class="conc-section">
      <div class="conc-header">Concentration: ${c.name} <span class="conc-pct">${c.complete}/${c.total} (${cPct}%)</span></div>
      ${c.note ? `<div class="conc-note">${c.note}</div>` : ""}
      ${renderSections(c.sections)}
    </div>`;
  }
  if (prog.concentrations && prog.concentrations.length > 0) {
    const names = prog.concentrations.map(c => c.name).join(", ");
    return `<div class="conc-hint">Concentrations available: ${names}</div>`;
  }
  return "";
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
        // For choose_n: if section is complete, mute unfulfilled alternatives
        const muted = !it.satisfied && s.status === COMPLETE;
        const ic = it.satisfied ? "\u2713" : muted ? "\u2015" : "\u2717";
        const c = it.satisfied ? "done" : muted ? "muted" : "todo";
        html += `<div class="item-row ${c}">
          <span class="req-icon">${ic}</span>
          <span>${it.title || ""} <span class="req-courses">${(it.codes||[]).join(", ")}</span></span>
        </div>`;
      }
    }
    if (s.options) {
      for (const o of s.options) {
        // If section is satisfied, mute unfulfilled alternatives
        const muted = !o.satisfied && s.status === COMPLETE;
        const ic = o.satisfied ? "\u2713" : muted ? "\u2015" : "\u2717";
        const c = o.satisfied ? "done" : muted ? "muted" : "todo";
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
        const clickable = !item.done ? ` data-add-code="${item.code}"` : "";
        sugHTML += `<div class="plan-item ${cls}"${clickable}>
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
//
// Three questions drive a rule-based first-semester recommendation.
// Rules mirror advisor_core.recommend_first_semester; see
// new_student_considerations/advisor_brief_fall_registration.md for evidence.

const HARD_LANDING_COURSES = new Set(["BIO-145", "MTH-135", "CS-125", "PHY-185", "CHM-121"]);
const STRICT_MONITORING_MAJORS = new Set(["EDU", "PHY", "EP", "BCM"]);
const QUANT_MAJORS = new Set(["MTH", "CS", "PHY", "EP", "BCM", "CHM", "DS"]);
const ALIGNMENT_MAP = {
  "BIO-145": new Set(["BIO", "BCM", "NEURO"]),
  "MTH-135": new Set(["MTH", "CS", "PHY", "EP", "DS"]),
  "CS-125":  new Set(["CS", "DS"]),
  "PHY-185": new Set(["PHY", "EP", "CHM", "BCM"]),
  "CHM-121": new Set(["CHM", "BCM", "BIO", "PHY", "EP"]),
};

function isAligned(course, majorCode, premed) {
  const n = normalize(course);
  const set = ALIGNMENT_MAP[n];
  if (set && set.has(majorCode)) return true;
  if (premed && (n === "BIO-145" || n === "CHM-121")) return true;
  return false;
}

function pickF2YEntry(majorCode, premed, prep) {
  if (!majorCode) return null;
  const allEntries = (DATA.first_two_years && DATA.first_two_years.entries) || [];
  const entries = allEntries.filter(e =>
    (e.match_major_codes || []).includes(majorCode));
  if (!entries.length) return null;
  function score(e) {
    let s = 0;
    const cond = e.conditions || {};
    const pathways = cond.pathways || [];
    if (premed && pathways.includes("premed")) s += 100;
    if (cond.intake_only && (prep === "typical" || prep === "under")) s += 50;
    if (!Object.keys(cond).length && prep === "well") s += 30;
    if (e.default) s += 5;
    return s;
  }
  entries.sort((a, b) => score(b) - score(a));
  return entries[0];
}

const FIRST_YEAR_SEMINAR = "FS-110";

function normalizeMajorCodes(codes) {
  if (codes == null) return [];
  if (typeof codes === "string") codes = [codes];
  const seen = [];
  for (const c of codes) {
    if (!c) continue;
    const cu = c.toUpperCase();
    if (!seen.includes(cu)) seen.push(cu);
  }
  const real = seen.filter(c => c !== "EXPLORATORY");
  return real.length ? real : seen;
}

function recommendFirstSemester(majorCodes, prep, premed, certainty) {
  const codes = normalizeMajorCodes(majorCodes);
  const isExploratory = !codes.length || (codes.length === 1 && codes[0] === "EXPLORATORY");
  prep = (prep || "typical").toLowerCase();
  certainty = (certainty || "committed").toLowerCase();
  const notes = [];
  const flags = [];
  let stackingNote = "";

  if (isExploratory) {
    const courses = [FIRST_YEAR_SEMINAR, "MTH-100 or STA-100",
                     "Writing-emphasis humanities (WE)", "Breadth natural science"];
    if (prep === "under")
      notes.push("Under-prepared: lean on foundational 100-level courses and maximize disciplinary diversity.");
    else if (prep === "well")
      notes.push("Well-prepared: consider a 200-level course in a plausible major area as a probe.");
    return { courses, notes, monitor_flags: flags, stacking_note: stackingNote };
  }

  const primary = codes[0];
  const multi = codes.length > 1;

  let courses = [];
  for (const mc of codes) {
    const entry = pickF2YEntry(mc, premed, prep);
    const y1f = ((entry || {}).semesters || {}).y1_fall || {};
    const ess = [...(y1f.essential || [])];
    const sug = [...(y1f.suggested || [])];
    for (const c of ess) if (!courses.includes(c)) courses.push(c);
    if (ess.length === 0) {
      for (const c of sug) if (!courses.includes(c)) courses.push(c);
    } else if (!multi && prep === "well" && certainty === "committed") {
      for (const c of sug) if (!courses.includes(c)) courses.push(c);
    }
  }

  if (multi)
    notes.push("Plan covers gateway courses for " + codes.join(", ") + " to keep all interests open.");

  // (a) BIO-155 → BIO-100 unless prep=well
  if (prep !== "well") {
    const replaced = [];
    let swapped = false;
    for (const c of courses) {
      const n = normalize(c);
      if (n === "BIO-155") { replaced.push("BIO-100"); swapped = true; }
      else if (n === "BIO-155L") { /* drop */ }
      else replaced.push(c);
    }
    if (swapped) notes.push("Swapped BIO-155 for BIO-100 given prep level.");
    courses = replaced;
  }

  // (b) MTH-135 gating
  if (courses.some(c => normalize(c) === "MTH-135")) {
    const quant = codes.some(mc => QUANT_MAJORS.has(mc));
    if (!(prep === "well" && quant && certainty === "committed")) {
      courses = courses.filter(c => normalize(c) !== "MTH-135");
      if (quant) {
        courses.push("MTH-130 or STA-100 (Calc prep)");
        notes.push("Deferred MTH-135 — rebuild calc readiness in fall, start 135 spring.");
      } else {
        notes.push("MTH-135 removed: not required in fall for this interest.");
      }
    }
  }

  // (c) BIO + CHM only when premed
  const hasBio = courses.some(c => normalize(c).startsWith("BIO-1"));
  const hasChm = courses.some(c => normalize(c).startsWith("CHM-121"));
  if (hasBio && hasChm && !premed) {
    courses = courses.filter(c => !normalize(c).startsWith("CHM-121"));
    notes.push("Dropped CHM-121 — pair with BIO in fall only for pre-med timing.");
  }

  // (d) Certainty: exploring/leaning trims to one aligned hard-landing course
  if (certainty === "exploring" || certainty === "leaning") {
    const hardInPlan = courses.filter(c => HARD_LANDING_COURSES.has(normalize(c)));
    if (hardInPlan.length >= 2) {
      const aligned = hardInPlan.filter(c => isAligned(c, primary, premed));
      const keep = aligned.length ? aligned[0] : hardInPlan[0];
      const moved = hardInPlan.filter(c => c !== keep);
      for (const c of moved) {
        courses = courses.filter(x => x !== c);
        const lab = c + "L";
        courses = courses.filter(x => x !== lab);
      }
      stackingNote = (certainty === "exploring" ? "Exploring" : "Leaning") +
                     ": held back " + moved.join(", ") + " to keep pivot options open.";
    }
    if (certainty === "exploring" && courses.length < 4) {
      const hasBreadth = courses.some(c => /breadth|WE/i.test(String(c)));
      if (!hasBreadth) courses.push("Breadth / GE course");
    }
  }

  // Always-on stacking safety
  const hardInPlan2 = courses.filter(c => HARD_LANDING_COURSES.has(normalize(c)));
  if (hardInPlan2.length >= 2 && !stackingNote) {
    const aligned = hardInPlan2.filter(c => isAligned(c, primary, premed));
    const keep = aligned.length ? aligned[0] : hardInPlan2[0];
    const moved = hardInPlan2.filter(c => c !== keep);
    for (const c of moved) {
      courses = courses.filter(x => x !== c);
      const lab = c + "L";
      courses = courses.filter(x => x !== lab);
    }
    stackingNote = "Unstacked: moved " + moved.join(", ") +
                   " to a later term to avoid compound hard-landing risk in fall.";
  }

  // First-Year Seminar: required for every first-semester student
  if (!courses.some(c => normalize(c) === FIRST_YEAR_SEMINAR))
    courses.unshift(FIRST_YEAR_SEMINAR);

  // Diversity
  const depts = courses.map(c => prefixOf(normalize(c))).filter(Boolean);
  const uniq = new Set(depts);
  if (uniq.size <= 1 && courses.length)
    notes.push("Add at least one breadth course outside the interest area.");
  if (prep === "under") {
    const counts = {};
    for (const d of depts) counts[d] = (counts[d] || 0) + 1;
    const modeCount = Math.max(0, ...Object.values(counts));
    if (modeCount >= 3)
      notes.push("Under-prepared: reduce in-department load to ≤2 courses and add breadth.");
  }

  // Midterm-F monitoring flags
  for (const c of courses) {
    const n = normalize(c);
    if (!HARD_LANDING_COURSES.has(n)) continue;
    let alignedTo = null;
    for (const mc of codes) if (isAligned(c, mc, premed)) { alignedTo = mc; break; }
    if (!alignedTo && !(premed && (n === "BIO-145" || n === "CHM-121"))) continue;
    const strict = STRICT_MONITORING_MAJORS.has(alignedTo);
    flags.push({
      course: n,
      strict,
      message: `Priority midterm-F monitoring in ${n}. ` + (strict
        ? `Declared ${alignedTo} interest: aligned-fail retention penalty is materially above the pooled mean — treat an F at midterm as the sharpest single triage signal.`
        : "An F at midterm is the retention triage threshold (D recovers at ~45% to C-or-better).")
    });
  }

  return { courses, notes, monitor_flags: flags, stacking_note: stackingNote };
}

function getIntakeSchema() {
  if (DATA.intake && DATA.intake._default) return DATA.intake._default;
  return {
    questions: [
      { id: "interest_majors", type: "major_multiselect", text: "Interest area(s)", include_exploratory: true },
      { id: "certainty", type: "choice", text: "Commitment to this path", options: [
          { value: "exploring", label: "Exploring" },
          { value: "leaning",   label: "Leaning" },
          { value: "committed", label: "Committed" },
        ]},
      { id: "prep_level", type: "choice", text: "Preparedness for college-level work", options: [
          { value: "well",    label: "More prepared than typical" },
          { value: "typical", label: "Typical preparedness" },
          { value: "under",   label: "Under-prepared" },
        ]},
      { id: "premed", type: "yes_no", text: "Interested in medicine (pre-med, PA, PT/DPT)?",
        show_when: { interest_major_code_in: ["BIO", "CHM", "BCM", "KIN", "NEURO", "PSY"] } }
    ]
  };
}

function buildMajorOptions() {
  const opts = ['<option value="EXPLORATORY">— Exploratory / Unsure —</option>'];
  const seen = new Set();
  const byName = [];
  for (const [pid, prog] of Object.entries(DATA.programs || {})) {
    if (prog.program_type !== "major") continue;
    if (!prog.major_code || seen.has(prog.major_code)) continue;
    seen.add(prog.major_code);
    byName.push({ code: prog.major_code, name: prog.name || pid, pid });
  }
  byName.sort((a, b) => a.name.localeCompare(b.name));
  for (const m of byName)
    opts.push(`<option value="${m.code}" data-pid="${m.pid}">${m.name} (${m.code})</option>`);
  return opts.join("");
}

function updateWizInterestRmVisibility(container) {
  const rows = container.querySelectorAll(".wiz-interest-row");
  const multi = rows.length > 1;
  rows.forEach(r => {
    const rm = r.querySelector(".wiz-interest-rm");
    if (rm) rm.style.visibility = multi ? "visible" : "hidden";
  });
}

function addWizInterestRow(container, optsHtml) {
  const row = document.createElement("div");
  row.className = "wiz-interest-row";
  row.style.cssText = "display:flex;gap:6px;align-items:center;margin-bottom:6px";
  row.innerHTML = `<select class="wiz-interest-sel" style="flex:1;padding:6px 8px;font-size:13px">${optsHtml}</select>` +
                  `<button type="button" class="wiz-interest-rm" style="padding:4px 10px;font-size:14px;line-height:1" title="Remove">×</button>`;
  row.querySelector(".wiz-interest-rm").onclick = () => {
    const rows = container.querySelectorAll(".wiz-interest-row");
    if (rows.length > 1) {
      row.remove();
      updateWizInterestRmVisibility(container);
      updateWizVisibility();
    }
  };
  row.querySelector(".wiz-interest-sel").addEventListener("change", updateWizVisibility);
  container.appendChild(row);
  updateWizInterestRmVisibility(container);
}

function getWizSelectedCodes() {
  const sels = document.querySelectorAll("#wiz-interests-container .wiz-interest-sel");
  const codes = [];
  for (const s of sels) if (s.value && !codes.includes(s.value)) codes.push(s.value);
  return codes;
}

function updateWizVisibility() {
  const intake = getIntakeSchema();
  const codes = getWizSelectedCodes();
  const realCodes = codes.filter(c => c !== "EXPLORATORY");
  for (const q of (intake.questions || [])) {
    const sw = q.show_when;
    if (!sw) continue;
    const el = document.querySelector(`.wiz-question[data-qid="${q.id}"]`);
    if (!el) continue;
    let show = false;
    if (sw.interest_major_code_in)
      show = realCodes.some(c => sw.interest_major_code_in.includes(c));
    el.style.display = show ? "" : "none";
  }
}

function showIntakeWizard() {
  const intake = getIntakeSchema();
  const modal = document.getElementById("wizard-modal");
  const body  = document.getElementById("wizard-body");

  const optsHtml = buildMajorOptions();
  const html = [];

  for (const q of (intake.questions || [])) {
    const sub = q.subtext ? `<div style="color:#64748b;font-size:11px;margin-top:2px">${q.subtext}</div>` : "";
    html.push(`<div class="wiz-question" data-qid="${q.id}" style="margin-bottom:18px">
      <div style="font-weight:500;margin-bottom:8px">${q.text}</div>${sub}`);
    if (q.type === "major_multiselect") {
      html.push(`<div id="wiz-interests-container"></div>`);
      html.push(`<button type="button" id="wiz-add-interest" class="small-btn" style="margin-top:4px">+ Add another area</button>`);
    } else if (q.type === "major_select") {
      html.push(`<select id="wiz_${q.id}" style="margin-top:6px;padding:6px 8px;font-size:13px;min-width:280px">${optsHtml}</select>`);
    } else if (q.type === "choice") {
      for (const opt of (q.options || []))
        html.push(`<label style="display:block;margin:4px 0;font-size:13px"><input type="radio" name="wiz_${q.id}" value="${opt.value}"> ${opt.label}</label>`);
    } else {
      html.push(`<label style="margin-right:14px;font-size:13px"><input type="radio" name="wiz_${q.id}" value="yes"> Yes</label>`);
      html.push(`<label style="font-size:13px"><input type="radio" name="wiz_${q.id}" value="no"> No</label>`);
    }
    html.push(`</div>`);
  }
  body.innerHTML = html.join("");

  const interestsContainer = document.getElementById("wiz-interests-container");
  if (interestsContainer) {
    addWizInterestRow(interestsContainer, optsHtml);
    const addBtn = document.getElementById("wiz-add-interest");
    if (addBtn) addBtn.onclick = () => addWizInterestRow(interestsContainer, optsHtml);
  }
  updateWizVisibility();

  modal.classList.add("visible");
}

function submitWizard() {
  const modal = document.getElementById("wizard-modal");

  const codes = getWizSelectedCodes();
  const realCodes = codes.filter(c => c !== "EXPLORATORY");
  const prep = (document.querySelector('input[name="wiz_prep_level"]:checked') || {}).value;
  if (!prep) { alert("Select a preparedness level."); return; }
  const certainty = (document.querySelector('input[name="wiz_certainty"]:checked') || {}).value || "committed";
  const hpEl = document.querySelector('input[name="wiz_health_pathway"]:checked');
  const hpQuestion = document.querySelector('.wiz-question[data-qid="health_pathway"]');
  const hpValue = hpQuestion && hpQuestion.style.display !== "none" && hpEl ? hpEl.value : "none";
  // Only MD/DO pre-med triggers BIO+CHM-together in fall (MCAT biochem timing).
  const premed = hpValue === "premed";

  const rec = recommendFirstSemester(codes.length ? codes : ["EXPLORATORY"], prep, premed, certainty);

  modal.classList.remove("visible");

  // Set the major dropdown (if a real major was picked).
  if (realCodes.length) {
    const selects = document.querySelectorAll("#major-slots .major-select");
    for (let i = 0; i < realCodes.length; i++) {
      if (i >= selects.length) { addMajorSlot(); }
    }
    const selects2 = document.querySelectorAll("#major-slots .major-select");
    for (let i = 0; i < realCodes.length && i < selects2.length; i++) {
      const code = realCodes[i];
      const pid = (() => {
        for (const [pid, prog] of Object.entries(DATA.programs || {}))
          if (prog.program_type === "major" && prog.major_code === code) return pid;
        return "";
      })();
      if (pid && DATA.programs[pid]) selects2[i].value = pid;
    }
  }
  updatePathways();
  if (hpValue && hpValue !== "none") {
    document.querySelectorAll(".pw-check input").forEach(cb => {
      if (cb.value === hpValue) cb.checked = true;
    });
  }

  // Split recommender output into specific codes vs placeholders.
  const termCode = pickUpcomingFallTerm();
  const termLabel = termCode && DATA.schedules && DATA.schedules[termCode]
                    ? DATA.schedules[termCode].term : null;
  const specifics = [];
  const placeholders = [];
  for (const c of rec.courses) {
    const resolved = resolveIntakePlaceholder(c, termCode);
    if (resolved.isPlaceholder) placeholders.push(resolved);
    else specifics.push(c);
  }

  // Pre-populate first-semester courses (specifics only)
  const semContainer = document.getElementById("plan-semesters");
  semContainer.innerHTML = "";
  addPlanSemester(PLAN_SEM_LABELS[1], specifics.join("\n"), false, 1);
  for (let i = 2; i <= 8; i++) addPlanSemester(PLAN_SEM_LABELS[i], "", false, i);

  // Render placeholder suggestions below sem-1 textarea
  const sem1 = document.querySelector('#plan-semesters .plan-semester[data-sem-num="1"]');
  const phEl = sem1 && sem1.querySelector(".plan-intake-placeholders");
  if (phEl) renderIntakePlaceholders(phEl, placeholders, termLabel);

  // Render the combined note (stacking + notes + flags)
  const noteEl = document.getElementById("route-note");
  const parts = [];
  if (rec.stacking_note) parts.push(`<div><strong>Stacking:</strong> ${rec.stacking_note}</div>`);
  for (const n of rec.notes) parts.push(`<div>• ${n}</div>`);
  for (const f of rec.monitor_flags) {
    const tag = f.strict ? "Strict monitoring" : "Monitor";
    parts.push(`<div><strong>${tag} (${f.course}):</strong> ${f.message}</div>`);
  }
  if (parts.length) {
    noteEl.innerHTML = parts.join("");
    noteEl.style.display = "block";
  } else {
    noteEl.style.display = "none";
    noteEl.innerHTML = "";
  }

  runCheck();
}

function closeWizard() {
  document.getElementById("wizard-modal").classList.remove("visible");
}

function pickUpcomingFallTerm() {
  const schedules = DATA.schedules || {};
  const falls = Object.keys(schedules).filter(k => /^fall_/i.test(k)).sort();
  if (falls.length) return falls[falls.length - 1];
  const any = Object.keys(schedules).sort();
  return any[any.length - 1] || null;
}

function resolveIntakePlaceholder(text, termCode) {
  const sd = (DATA.schedules || {})[termCode];
  const offered = (sd && sd.courses) || {};
  const trim = String(text).trim();

  // Already a specific course code
  if (/^[A-Z]{2,4}-\d+L?$/.test(trim)) return { isPlaceholder: false };

  // "100-level ART", "200 level CRW"
  let m = trim.match(/^(\d+)[- ]level\s+([A-Z]{2,4})/i);
  if (m) {
    const level = parseInt(m[1], 10), prefix = m[2].toUpperCase();
    const candidates = Object.entries(offered)
      .filter(([c]) => {
        if (!c.startsWith(prefix + "-")) return false;
        const num = parseInt(String(c.split("-")[1] || "").replace(/L$/, ""), 10);
        return num >= level && num < level + 100;
      })
      .map(([c, info]) => ({ code: c, title: info.title || "" }));
    return { isPlaceholder: true, label: trim, candidates };
  }

  // "MTH-100 or STA-100" / "MTH-130 or STA-100 (Calc prep)"
  if (/^[A-Z]{2,4}-\d+(\s+or\s+[A-Z]{2,4}-\d+)+/i.test(trim)) {
    const codes = trim.match(/[A-Z]{2,4}-\d+/g) || [];
    const candidates = codes
      .filter(c => offered[c])
      .map(c => ({ code: c, title: (offered[c] || {}).title || "" }));
    return { isPlaceholder: true, label: trim, candidates };
  }

  // Writing-emphasis — filter by divisional area when the label names one
  if (/writing.emphasis|\bWE\b/i.test(trim)) {
    const HUMANITIES = new Set(["AAM", "CLA", "COM", "ENG", "HIS", "JPN", "PHL", "REL", "SPA"]);
    const FINE_ARTS  = new Set(["ARH", "ART", "CRW", "MU", "MUA", "THE"]);
    const SOC_SCI    = new Set(["ANT", "ECO", "GS", "POL", "PSY", "SOC"]);
    const wantHum = /humanit/i.test(trim);
    const wantFA  = /fine.?art/i.test(trim);
    const wantSS  = /social/i.test(trim);
    const candidates = [];
    for (const [c, info] of Object.entries(offered)) {
      if (!(info.sections || []).some(s => s.we)) continue;
      const parts = c.split("-");
      const num = parseInt(String(parts[1] || "").replace(/L$/, ""), 10);
      if (num >= 300) continue;
      if (wantHum && !HUMANITIES.has(parts[0])) continue;
      if (wantFA  && !FINE_ARTS.has(parts[0])) continue;
      if (wantSS  && !SOC_SCI.has(parts[0])) continue;
      candidates.push({ code: c, title: info.title || "" });
    }
    return { isPlaceholder: true, label: trim, candidates };
  }

  // Breadth natural science
  if (/breadth.*(natural|science)/i.test(trim)) {
    const nat = new Set(["BIO", "CHM", "PHY", "ENR", "DS", "CS", "MTH", "STA"]);
    const candidates = [];
    for (const [c, info] of Object.entries(offered)) {
      const parts = c.split("-");
      const num = parseInt(String(parts[1] || "").replace(/L$/, ""), 10);
      if (nat.has(parts[0]) && num < 300) candidates.push({ code: c, title: info.title || "" });
    }
    return { isPlaceholder: true, label: trim, candidates };
  }

  // Generic breadth / GE — too broad to enumerate meaningfully
  if (/breadth|\bGE\b/i.test(trim)) {
    return { isPlaceholder: true, label: trim, candidates: [] };
  }

  // Unknown non-course string — treat as placeholder with no resolutions
  return { isPlaceholder: true, label: trim, candidates: [] };
}

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderIntakePlaceholders(container, placeholders, termLabel) {
  if (!placeholders.length) {
    container.style.display = "none";
    container.innerHTML = "";
    return;
  }
  const parts = [];
  parts.push(`<div class="intake-ph-head">Suggested for ${termLabel ? escapeAttr(termLabel) : "next term"} (click to add):</div>`);
  for (const ph of placeholders) {
    parts.push(`<div class="intake-ph-block">`);
    parts.push(`<div class="intake-ph-label">${escapeAttr(ph.label)}</div>`);
    if (ph.candidates.length) {
      parts.push(`<div class="intake-ph-chips">`);
      for (const c of ph.candidates) {
        const title = c.title ? ` · ${escapeAttr(c.title)}` : "";
        parts.push(`<button type="button" class="intake-ph-chip" data-code="${escapeAttr(c.code)}">${escapeAttr(c.code)}${title}</button>`);
      }
      parts.push(`</div>`);
    } else {
      parts.push(`<div class="intake-ph-empty">No direct matches in the offered courses; browse the Schedule tab.</div>`);
    }
    parts.push(`</div>`);
  }
  container.innerHTML = parts.join("");
  container.style.display = "";
  for (const btn of container.querySelectorAll(".intake-ph-chip")) {
    btn.addEventListener("click", () => {
      const code = btn.dataset.code;
      const ta = container.closest(".plan-semester")?.querySelector(".sem-courses");
      if (!ta) return;
      const cur = ta.value.trim();
      ta.value = cur ? cur + "\n" + code : code;
      btn.disabled = true;
      btn.classList.add("added");
      runCheck();
    });
  }
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
  document.querySelectorAll("#major-slots .major-select").forEach(sel => {
    if (sel.value) selectedProgIds.push(sel.value);
  });
  document.querySelectorAll("#minor-slots .minor-select").forEach(sel => {
    if (sel.value) selectedProgIds.push(sel.value);
  });

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
    // Include non_course sections from selected concentrations
    const concId = getSelectedConcentrationForProgram(pid);
    if (concId && prog.concentrations) {
      const conc = prog.concentrations.find(c => c.id === concId);
      if (conc) {
        for (const sec of (conc.sections || [])) {
          if (sec.type !== "non_course") continue;
          const reqId = pid + "_conc_" + (sec.id || sec.label.replace(/\s+/g, "_").toLowerCase().slice(0, 40));
          if (seenIds.has(reqId)) continue;
          seenIds.add(reqId);
          items.push({ id: reqId, label: `${conc.name}: ${sec.label}`, description: sec.description || "" });
        }
      }
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

// ─── Concentration dropdowns ────────────────────────────────────────────────

function updateConcentrations() {
  document.querySelectorAll("#major-slots .major-select, #minor-slots .minor-select").forEach(sel => {
    const label = sel.closest("label");
    if (!label) return;
    const existing = label.querySelector(".conc-select-wrapper");
    const prevVal = existing ? (existing.querySelector(".conc-select")?.value || "") : "";
    if (existing) existing.remove();

    const progId = sel.value;
    if (!progId) return;
    const prog = DATA.programs[progId];
    if (!prog || !prog.concentrations || prog.concentrations.length === 0) return;

    const wrapper = document.createElement("div");
    wrapper.className = "conc-select-wrapper";
    const concSel = document.createElement("select");
    concSel.className = "conc-select";
    concSel.innerHTML = '<option value="">No concentration</option>';
    for (const conc of prog.concentrations) {
      const opt = document.createElement("option");
      opt.value = conc.id;
      opt.textContent = conc.name;
      concSel.appendChild(opt);
    }
    if (prevVal && [...concSel.options].some(o => o.value === prevVal)) {
      concSel.value = prevVal;
    }
    wrapper.appendChild(concSel);
    label.appendChild(wrapper);
  });
}

function getSelectedConcentrationForProgram(progId) {
  const allSelects = document.querySelectorAll("#major-slots .major-select, #minor-slots .minor-select");
  for (const sel of allSelects) {
    if (sel.value !== progId) continue;
    const concSel = sel.closest("label")?.querySelector(".conc-select");
    if (concSel && concSel.value) return concSel.value;
  }
  return null;
}

function updatePathways() {
  const selectedProgIds = [];
  const selectedMajorCodes = new Set();
  document.querySelectorAll("#major-slots .major-select").forEach(sel => {
    if (sel.value) {
      selectedProgIds.push(sel.value);
      const prog = DATA.programs[sel.value];
      if (prog && prog.major_code) selectedMajorCodes.add(prog.major_code);
    }
  });

  const pwContainer = document.getElementById("pathways");
  // Remember which were checked
  const checked = new Set();
  pwContainer.querySelectorAll("input:checked").forEach(cb => checked.add(cb.value));

  pwContainer.innerHTML = "";
  let count = 0;
  for (const [id, pw] of Object.entries(DATA.pathways || {})) {
    const relatedCodes = pw.related_major_codes || [];
    const relatedProgs = pw.related_programs || [];
    // Only show pathways relevant to selected programs (by major_code or program ID)
    const matchesByCode = relatedCodes.length > 0 && relatedCodes.some(c => selectedMajorCodes.has(c));
    const matchesByProg = relatedProgs.length > 0 && relatedProgs.some(rp => selectedProgIds.includes(rp));
    if (selectedProgIds.length > 0 && (relatedCodes.length > 0 || relatedProgs.length > 0)
        && !matchesByCode && !matchesByProg) continue;
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
    <div class="plan-intake-placeholders" style="display:none"></div>
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

// ─── Advisor Notes ──────────────────────────────────────────────────────────

function addAdvisorNote(date, text) {
  const container = document.getElementById("advisor-notes");
  if (!date) {
    const now = new Date();
    date = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
  }
  const div = document.createElement("div");
  div.className = "advisor-note";
  div.innerHTML = `<div class="note-header">
    <input type="date" class="note-date" value="${date}">
    <button class="prog-remove-btn" onclick="this.closest('.advisor-note').remove()" title="Remove note">\u00d7</button>
  </div>
  <textarea class="note-text" rows="3" placeholder="Meeting notes..."></textarea>`;
  container.appendChild(div);
  if (text) div.querySelector(".note-text").value = text;
  // Scroll the new note into view
  div.querySelector(".note-text").focus();
}

// ─── Dynamic Program Slots ──────────────────────────────────────────────────

function populateMajorSelect(sel) {
  const catYear = document.getElementById("catalog-year")?.value || "";
  sel.innerHTML = '<option value="">Exploratory</option>';
  for (const m of (window._majorEntries || [])) {
    if (catYear && m.catalog_year !== catYear) continue;
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = m.name;
    sel.appendChild(opt);
  }
}

function populateMinorSelect(sel) {
  const catYear = document.getElementById("catalog-year")?.value || "";
  sel.innerHTML = '<option value="">Exploratory</option>';
  for (const m of (window._minorEntries || [])) {
    if (catYear && m.catalog_year !== catYear) continue;
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = m.name;
    sel.appendChild(opt);
  }
}

function addMajorSlot() {
  const container = document.getElementById("major-slots");
  if (container.querySelectorAll(".major-select").length >= 3) return;
  const label = document.createElement("label");
  const sel = document.createElement("select");
  sel.className = "major-select";
  populateMajorSelect(sel);
  const btn = document.createElement("button");
  btn.className = "prog-remove-btn";
  btn.title = "Remove";
  btn.textContent = "\u00d7";
  btn.onclick = () => { label.remove(); updatePathways(); buildOtherReqs(); runCheck(); };
  label.appendChild(sel);
  label.appendChild(btn);
  container.appendChild(label);
  // Hide "+" if at max
  if (container.querySelectorAll(".major-select").length >= 3) {
    document.querySelector("#major-group .prog-add-btn").style.display = "none";
  }
}

function addMinorSlot() {
  const container = document.getElementById("minor-slots");
  if (container.querySelectorAll(".minor-select").length >= 2) return;
  const label = document.createElement("label");
  const sel = document.createElement("select");
  sel.className = "minor-select";
  populateMinorSelect(sel);
  const btn = document.createElement("button");
  btn.className = "prog-remove-btn";
  btn.title = "Remove";
  btn.textContent = "\u00d7";
  btn.onclick = () => { label.remove(); document.querySelector("#minor-group .prog-add-btn").style.display = ""; runCheck(); };
  label.appendChild(sel);
  label.appendChild(btn);
  container.appendChild(label);
  if (container.querySelectorAll(".minor-select").length >= 2) {
    document.querySelector("#minor-group .prog-add-btn").style.display = "none";
  }
}

// ─── Schedule tab ───────────────────────────────────────────────────────────

const SCHED_COLORS = 8;
const SCHED_START_HOUR = 8;   // 8 AM
const SCHED_END_HOUR = 18;    // 6 PM
const SCHED_PX_PER_HOUR = 50;

// State: list of {code, sectionId, colorIdx}
let schedEntries = [];
let schedColorNext = 0;

function getScheduleData() {
  const termCode = document.getElementById("sched-term")?.value;
  return (DATA.schedules && DATA.schedules[termCode]) || null;
}

function onSchedTermChange() {
  buildSchedDatalist();
  // Clear entries that don't exist in new term
  const sd = getScheduleData();
  if (sd) {
    schedEntries = schedEntries.filter(e => sd.courses[e.code]);
  }
  renderSchedCourses();
  renderSchedCalendar();
}

function buildSchedDatalist() {
  const dl = document.getElementById("sched-datalist");
  dl.innerHTML = "";
  const sd = getScheduleData();
  if (!sd) return;
  const sorted = Object.keys(sd.courses).sort();
  for (const code of sorted) {
    const c = sd.courses[code];
    // Only include courses with scheduled meetings
    if (c.sections.some(s => s.meetings.length > 0)) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.label = `${code} — ${c.title}`;
      dl.appendChild(opt);
    }
  }
}

function schedAddCourse() {
  const input = document.getElementById("sched-search");
  const raw = input.value.trim();
  if (!raw) return;
  const code = normalize(raw);
  const sd = getScheduleData();
  if (!sd || !sd.courses[code]) {
    input.value = "";
    return;
  }
  if (schedEntries.some(e => e.code === code)) {
    input.value = "";
    return;
  }
  // Default to first section with meetings
  const defaultSec = sd.courses[code].sections.find(s => s.meetings.length > 0)
                  || sd.courses[code].sections[0];
  schedEntries.push({ code, sectionId: defaultSec.id, colorIdx: schedColorNext++ % SCHED_COLORS });
  input.value = "";
  renderSchedCourses();
  renderSchedCalendar();
  syncSchedToPlan();
}

function schedRemoveCourse(code) {
  schedEntries = schedEntries.filter(e => e.code !== code);
  renderSchedCourses();
  renderSchedCalendar();
  syncSchedToPlan();
}

function schedChangeSection(code, sectionId) {
  const entry = schedEntries.find(e => e.code === code);
  if (entry) entry.sectionId = sectionId;
  renderSchedCalendar();
  syncSchedToPlan();
}

function renderSchedCourses() {
  const el = document.getElementById("sched-courses");
  const sd = getScheduleData();
  if (!sd) { el.innerHTML = ""; return; }
  let html = "";
  for (const entry of schedEntries) {
    const course = sd.courses[entry.code];
    if (!course) continue;
    const sections = course.sections.filter(s => s.meetings.length > 0);
    let secOptions = "";
    for (const s of sections) {
      const mtg = s.meetings.map(m => `${m.days} ${m.start}-${m.end}`).join(", ");
      const sel = s.id === entry.sectionId ? " selected" : "";
      secOptions += `<option value="${s.id}"${sel}>${s.id} — ${s.instructor} — ${mtg}</option>`;
    }
    html += `<div class="sched-course">
      <span class="sched-course-code" style="color: var(--sched-c${entry.colorIdx})">${entry.code}</span>
      <span class="sched-course-title">${course.title}</span>
      <select onchange="schedChangeSection('${entry.code}', this.value)">${secOptions}</select>
      <button class="prog-remove-btn" onclick="schedRemoveCourse('${entry.code}')" title="Remove">\u00d7</button>
    </div>`;
  }
  el.innerHTML = html;
}

function timeToMinutes(t) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function minutesToDisplay(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  const ap = h >= 12 ? "PM" : "AM";
  const h12 = h > 12 ? h - 12 : (h === 0 ? 12 : h);
  return `${h12}:${String(m).padStart(2, "0")} ${ap}`;
}

function renderSchedCalendar() {
  const sd = getScheduleData();
  const dayBodies = {};
  document.querySelectorAll(".sched-day-col").forEach(col => {
    const day = col.dataset.day;
    const body = col.querySelector(".sched-day-body");
    body.innerHTML = "";
    dayBodies[day] = body;
  });

  const totalHours = SCHED_END_HOUR - SCHED_START_HOUR;
  const totalPx = totalHours * SCHED_PX_PER_HOUR;

  // Set heights
  for (const body of Object.values(dayBodies)) {
    body.style.height = totalPx + "px";
  }

  // Hour lines
  for (const body of Object.values(dayBodies)) {
    for (let h = SCHED_START_HOUR; h <= SCHED_END_HOUR; h++) {
      const line = document.createElement("div");
      line.className = "sched-hour-line";
      line.style.top = ((h - SCHED_START_HOUR) * SCHED_PX_PER_HOUR) + "px";
      body.appendChild(line);
    }
  }

  // Time labels
  const timeCol = document.getElementById("sched-time-col");
  timeCol.innerHTML = "";
  timeCol.style.height = (totalPx + 24) + "px"; // +header
  for (let h = SCHED_START_HOUR; h <= SCHED_END_HOUR; h++) {
    const label = document.createElement("div");
    label.className = "sched-time-label";
    label.style.top = (24 + (h - SCHED_START_HOUR) * SCHED_PX_PER_HOUR) + "px";
    const ap = h >= 12 ? "PM" : "AM";
    const h12 = h > 12 ? h - 12 : h;
    label.textContent = `${h12}${ap}`;
    timeCol.appendChild(label);
  }

  if (!sd) return;

  // Collect all blocks for overlap detection
  const allBlocks = []; // {day, startMin, endMin, code, entry}
  for (const entry of schedEntries) {
    const course = sd.courses[entry.code];
    if (!course) continue;
    const sec = course.sections.find(s => s.id === entry.sectionId);
    if (!sec) continue;
    for (const mtg of sec.meetings) {
      const startMin = timeToMinutes(mtg.start);
      const endMin = timeToMinutes(mtg.end);
      for (const dayChar of mtg.days) {
        allBlocks.push({ day: dayChar, startMin, endMin, code: entry.code, colorIdx: entry.colorIdx,
                         start: mtg.start, end: mtg.end, location: mtg.location });
      }
    }
  }

  // Detect overlaps
  const overlapPairs = new Set();
  for (let i = 0; i < allBlocks.length; i++) {
    for (let j = i + 1; j < allBlocks.length; j++) {
      const a = allBlocks[i], b = allBlocks[j];
      if (a.day === b.day && a.startMin < b.endMin && b.startMin < a.endMin) {
        overlapPairs.add(i);
        overlapPairs.add(j);
      }
    }
  }

  // Show overlap alert
  const alertEl = document.getElementById("sched-overlap-alert");
  if (overlapPairs.size > 0) {
    const conflictCodes = [...new Set([...overlapPairs].map(i => allBlocks[i].code))];
    alertEl.textContent = `Time conflict: ${conflictCodes.join(", ")}`;
    alertEl.style.display = "";
  } else {
    alertEl.style.display = "none";
  }

  // Render blocks
  const startBase = SCHED_START_HOUR * 60;
  for (let i = 0; i < allBlocks.length; i++) {
    const b = allBlocks[i];
    const body = dayBodies[b.day];
    if (!body) continue;
    const top = (b.startMin - startBase) / 60 * SCHED_PX_PER_HOUR;
    const height = (b.endMin - b.startMin) / 60 * SCHED_PX_PER_HOUR;
    const block = document.createElement("div");
    block.className = `sched-block sched-color-${b.colorIdx}${overlapPairs.has(i) ? " overlap" : ""}`;
    block.style.top = top + "px";
    block.style.height = Math.max(height, 14) + "px";
    block.title = `${b.code}\n${minutesToDisplay(b.startMin)}-${minutesToDisplay(b.endMin)}\n${b.location}`;
    block.innerHTML = `<div class="sched-block-code">${b.code}</div>`
      + (height >= 28 ? `<div class="sched-block-time">${minutesToDisplay(b.startMin)}-${minutesToDisplay(b.endMin)}</div>` : "");
    body.appendChild(block);
  }
}

// ── Plan tab integration ──────────────────────────────────────────────────

function getSchedPlanSemNum() {
  const sel = document.getElementById("sched-plan-sem");
  return sel ? parseInt(sel.value) || null : null;
}

function syncSchedToPlan() {
  const semNum = getSchedPlanSemNum();
  if (!semNum) return;
  const semEl = document.querySelector(`#plan-semesters .plan-semester[data-sem-num="${semNum}"]`);
  if (!semEl) return;
  const ta = semEl.querySelector(".sem-courses");
  if (!ta || ta.readOnly) return;

  // Merge: keep existing non-schedule courses, add schedule courses
  const existingLines = ta.value.split("\n").map(l => l.trim()).filter(Boolean);
  const schedCodes = new Set(schedEntries.map(e => normalize(e.code)));
  // Keep lines that aren't from our schedule set (manually typed courses)
  const kept = existingLines.filter(l => {
    const n = normalize(l);
    return !schedCodes.has(n) && !ta.dataset.schedCodes?.split(",").includes(n);
  });
  const newLines = [...kept, ...schedEntries.map(e => e.code)];
  ta.value = newLines.join("\n");
  ta.dataset.schedCodes = [...schedCodes].join(",");
  runCheck();
}

function syncSchedFromPlan() {
  const semNum = getSchedPlanSemNum();
  if (!semNum) return;
  const sd = getScheduleData();
  if (!sd) return;

  const semEl = document.querySelector(`#plan-semesters .plan-semester[data-sem-num="${semNum}"]`);
  if (!semEl) return;
  const ta = semEl.querySelector(".sem-courses");
  if (!ta) return;

  const codes = parseCourses(ta.value);
  // Load courses that exist in the current schedule
  schedEntries = [];
  schedColorNext = 0;
  for (const code of codes) {
    if (sd.courses[code] && !schedEntries.some(e => e.code === code)) {
      const defaultSec = sd.courses[code].sections.find(s => s.meetings.length > 0)
                      || sd.courses[code].sections[0];
      if (defaultSec) {
        schedEntries.push({ code, sectionId: defaultSec.id, colorIdx: schedColorNext++ % SCHED_COLORS });
      }
    }
  }
  renderSchedCourses();
  renderSchedCalendar();

  // Detect term from semester label
  const termSel = document.getElementById("sched-term");
  if (termSel && semNum) {
    const isFall = semNum % 2 === 1;
    const wanted = isFall ? "fall" : "spring";
    for (const opt of termSel.options) {
      if (opt.value.startsWith(wanted)) { termSel.value = opt.value; break; }
    }
    buildSchedDatalist();
  }
}

function initScheduleTab() {
  const termSel = document.getElementById("sched-term");
  if (!DATA.schedules) return;
  for (const [code, sched] of Object.entries(DATA.schedules)) {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = sched.term;
    termSel.appendChild(opt);
  }

  // Plan semester dropdown
  const planSemSel = document.getElementById("sched-plan-sem");
  for (const [num, lbl] of Object.entries(PLAN_SEM_LABELS)) {
    const opt = document.createElement("option");
    opt.value = num;
    opt.textContent = lbl;
    planSemSel.appendChild(opt);
  }

  buildSchedDatalist();
  renderSchedCalendar();

  // Allow Enter key in search
  document.getElementById("sched-search").addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); schedAddCourse(); }
  });
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
  const majorEntries = [], minorEntries = [];
  for (const [id, p] of Object.entries(DATA.programs)) {
    const entry = { id, name: p.name, catalog_year: p.catalog_year || "", program_type: p.program_type || "" };
    if (["major", "collateral", "certificate"].includes(p.program_type)) majorEntries.push(entry);
    else if (p.program_type === "minor") minorEntries.push(entry);
  }
  majorEntries.sort((a, b) => a.name.localeCompare(b.name));
  minorEntries.sort((a, b) => a.name.localeCompare(b.name));

  // Store for dynamic slot creation
  window._majorEntries = majorEntries;
  window._minorEntries = minorEntries;

  // Populate catalog year dropdown (must happen before program selects)
  const catalogYears = [...new Set(
    Object.values(DATA.programs).map(p => p.catalog_year).filter(Boolean)
  )].sort();
  const catYearSel = document.getElementById("catalog-year");
  for (const y of catalogYears) {
    const opt = document.createElement("option");
    opt.value = y; opt.textContent = y;
    catYearSel.appendChild(opt);
  }
  catYearSel.value = catalogYears[catalogYears.length - 1] || "";

  // Populate the initial major and minor selects
  populateMajorSelect(document.querySelector("#major-slots .major-select"));
  populateMinorSelect(document.querySelector("#minor-slots .minor-select"));

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

  // Schedule tab
  initScheduleTab();

  // Catalog year change: re-populate program dropdowns, try to preserve selections
  document.getElementById("catalog-year").addEventListener("change", () => {
    document.querySelectorAll("#major-slots .major-select").forEach(sel => {
      const prevProg = sel.value ? DATA.programs[sel.value] : null;
      populateMajorSelect(sel);
      if (prevProg) {
        const match = [...sel.options].find(o => {
          const p = DATA.programs[o.value];
          return p && p.name === prevProg.name && p.program_type === prevProg.program_type;
        });
        if (match) sel.value = match.value;
      }
    });
    document.querySelectorAll("#minor-slots .minor-select").forEach(sel => {
      const prevProg = sel.value ? DATA.programs[sel.value] : null;
      populateMinorSelect(sel);
      if (prevProg) {
        const match = [...sel.options].find(o => {
          const p = DATA.programs[o.value];
          return p && p.name === prevProg.name && p.program_type === prevProg.program_type;
        });
        if (match) sel.value = match.value;
      }
    });
    updateConcentrations(); updatePathways(); buildOtherReqs(); runCheck();
  });

  // Filter pathways and rebuild other reqs when program selection changes
  // Use event delegation on the programs-grid container
  document.getElementById("programs-grid").addEventListener("change", () => {
    updateConcentrations(); updatePathways(); buildOtherReqs();
  });

  // Initial other reqs
  buildOtherReqs();

  // Auto-check on changes in left panel (programs, pathways, transfer WE)
  document.getElementById("input-panel").addEventListener("change", () => runCheck());
  document.getElementById("input-panel").addEventListener("input", debounce(runCheck, 500));

  // Auto-check on changes in plan semesters (course textareas)
  const planSems = document.getElementById("plan-semesters");
  planSems.addEventListener("input", debounce(runCheck, 500));

  // Click-to-add on suggestions
  planSems.addEventListener("click", e => {
    const item = e.target.closest("[data-add-code]");
    if (!item) return;
    const code = item.dataset.addCode;
    const sem = item.closest(".plan-semester");
    const ta = sem?.querySelector(".sem-courses");
    if (!ta || ta.readOnly) return;
    const val = ta.value.trim();
    ta.value = val ? val + "\n" + code : code;
    runCheck();
  });

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
