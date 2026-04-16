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
    const matching = [...taken].filter(x =>
      !isAuxiliary(x) && (!pfxs.size || pfxs.has(prefixOf(x))) && !excl.has(x));
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

// ─── Suggested Plan builder ──────────────────────────────────────────────────

const PLAN_SEM_LABELS = {
  1: "Fall \u2014 Year 1",   2: "Spring \u2014 Year 1",
  3: "Fall \u2014 Year 2",   4: "Spring \u2014 Year 2",
  5: "Fall \u2014 Year 3",   6: "Spring \u2014 Year 3",
  7: "Fall \u2014 Year 4",   8: "Spring \u2014 Year 4",
};

const F2Y_SEM_NUM = { y1_fall: 1, y1_spring: 2, y2_fall: 3, y2_spring: 4 };

function buildSuggestedPlan(selectedPrograms, takenSet, geResult, currentSem) {
  currentSem = currentSem || 1;
  const majorCode = findMajorCode(selectedPrograms);
  const shownCodes = new Set();
  const semBuckets = {};
  for (let i = 1; i <= 8; i++) semBuckets[i] = [];

  // F2Y entries
  const f2yEntries = findF2YEntries(selectedPrograms);
  for (const entry of f2yEntries) {
    const semesters = entry.semesters || {};
    for (const [key, semData] of Object.entries(semesters)) {
      const semNum = F2Y_SEM_NUM[key];
      if (!semNum) continue;
      for (const cat of ["essential", "suggested"]) {
        for (const item of (semData[cat] || [])) {
          const code = normalize(item);
          if (!/^[A-Z]+-\d/.test(code)) continue;
          if (shownCodes.has(code)) continue;
          shownCodes.add(code);
          const done = takenSet.has(code);
          const traj = majorCode ? trajectoryInfo(majorCode, code) : null;
          semBuckets[semNum].push({
            display: code, program: entry.label || "", category: cat,
            done, primary: code, isCode: true,
            pct: traj ? traj.pct : null, trajSem: traj ? traj.sem : null,
          });
        }
      }
    }
  }

  // FS-110
  const fysDone = geResult.fys && geResult.fys.complete;
  const fs110 = normalize("FS-110");
  if (!fysDone && !shownCodes.has(fs110)) {
    shownCodes.add(fs110);
    const done = takenSet.has(fs110);
    if (currentSem <= 1) {
      semBuckets[1].unshift({
        display: "FS-110 First Year Seminar", program: "", category: "essential",
        done, primary: fs110, isCode: true,
      });
    } else if (!done) {
      semBuckets[currentSem] = semBuckets[currentSem] || [];
      semBuckets[currentSem].push({
        display: "FS-110 First Year Seminar (overdue)", program: "", category: "essential",
        done: false, primary: fs110, isCode: true,
      });
    }
  }

  // Required courses from programs (not already placed by F2Y)
  for (const prog of selectedPrograms) {
    for (const sec of (prog.sections || [])) {
      if (sec.type === "all") {
        for (const item of (sec.items || [])) {
          const codes = (item.codes || []).map(normalize);
          const primaryCode = codes.find(c => !isAuxiliary(c)) || codes[0];
          if (!primaryCode || shownCodes.has(primaryCode)) continue;
          shownCodes.add(primaryCode);
          const done = takenSet.has(primaryCode);
          const traj = majorCode ? trajectoryInfo(majorCode, primaryCode) : null;
          const targetSem = traj && traj.sem ? traj.sem : 8;
          semBuckets[targetSem].push({
            display: `${primaryCode} ${item.title || ""}`.trim(),
            program: prog.name || "", category: "required",
            done, primary: primaryCode, isCode: true,
            pct: traj ? traj.pct : null, trajSem: traj ? traj.sem : null,
          });
        }
      }
    }
  }

  // GE fill-in hints for semesters 1-4
  const divNames = {
    fine_arts: "Fine Arts", humanities: "Humanities",
    social_sciences: "Social Sciences", nat_sci_math: "Natural Sciences & Math",
  };
  const pfxToDiv = {};
  for (const [dk, dn] of Object.entries(divNames)) {
    const sec = ((DATA.ge.divisional || {}).sections || {})[dk] || {};
    for (const pfx of (sec.prefixes || [])) pfxToDiv[pfx] = dk;
  }

  for (let semNum = 1; semNum <= 4; semNum++) {
    const items = semBuckets[semNum];
    const primaries = new Set(items.filter(it => it.primary && !isAuxiliary(it.primary)).map(it => it.primary));
    const slotsFilled = primaries.size;
    const geRemaining = Math.max(0, 4 - slotsFilled);
    if (geRemaining > 0) {
      const coveredDivs = new Set();
      for (const p of primaries) {
        const d = pfxToDiv[prefixOf(p)];
        if (d) coveredDivs.add(d);
      }
      const openDivs = [];
      for (const [dk, dn] of Object.entries(divNames)) {
        if (!coveredDivs.has(dk) && geResult[dk] && !geResult[dk].complete) openDivs.push(dn);
      }
      if (openDivs.length > 0) {
        const count = geRemaining === 1 ? "one GE course" : geRemaining === 2 ? "two GE courses" : `${geRemaining} GE courses`;
        const divList = openDivs.length <= 2 ? openDivs.join(" or ") : openDivs.slice(0, -1).join(", ") + ", or " + openDivs[openDivs.length - 1];
        semBuckets[semNum].push({
          display: `+ ${count} in ${divList}`,
          isHint: true, done: false,
        });
      }
    }
  }

  return { semBuckets, majorCode };
}

function findMajorCode(programs) {
  for (const p of programs) {
    if (p.program_type === "major" && p.major_code) return p.major_code;
  }
  return "";
}

function findF2YEntries(programs) {
  const f2y = DATA.first_two_years || { entries: [] };
  const entries = f2y.entries || f2y;
  if (!Array.isArray(entries)) return [];
  const result = [];
  for (const prog of programs) {
    const majorCode = prog.major_code || "";
    const progId = prog.id || "";
    for (const entry of entries) {
      const matchCodes = entry.match_major_codes || [];
      const matchIds = entry.match_program_ids || [];
      if (matchCodes.includes(majorCode) || matchIds.includes(progId)) {
        result.push(entry);
        break;
      }
    }
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

  document.querySelectorAll(".semester").forEach(semEl => {
    const label = semEl.querySelector(".sem-label").textContent.trim();
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
  let currentSem = null;
  const oldCourses = [];
  let inOldCourses = false;

  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s || s.startsWith("#")) continue;

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
  document.querySelectorAll(".pw-check input").forEach(cb => {
    cb.checked = pws.includes(cb.value);
  });

  let weVal = fields.TRANSFER_WE;
  if (weVal === "8 credits \u2014 max (3 WE)") weVal = "8\u201315 credits (3 WE)";
  const weSel = document.getElementById("transfer-we");
  if ([...weSel.options].some(o => o.value === weVal)) weSel.value = weVal;

  // Build semester grid
  const semContainer = document.getElementById("semesters");
  semContainer.innerHTML = "";
  const semData = semesters.length > 0 ? semesters
    : oldCourses.length > 0 ? [{ label: "Semester 1", courses: oldCourses }]
    : [];

  if (semData.length === 0) {
    addSemester("Transfer", "");
    for (let i = 1; i <= 4; i++) addSemester(`Semester ${i}`, "");
  } else {
    for (const sd of semData) {
      const completed = sd.hasCompleted && !sd.hasPlanned;
      addSemester(sd.label, sd.courses.join("\n"), completed);
    }
  }
  // Show pathways if a major was loaded
  const hasMajor = [1,2,3].some(i => document.getElementById(`major${i}`).value);
  document.getElementById("pathways-row").style.display = hasMajor ? "" : "none";
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
  document.querySelectorAll(".sem-courses").forEach(ta => {
    for (const c of parseCourses(ta.value)) allCourses.add(c);
  });

  return { progIds, activePw, taken: allCourses };
}

function runCheck() {
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

  // Render
  const resultsEl = document.getElementById("results");
  const emptyEl = document.getElementById("results-empty");

  if (progIds.length === 0 && taken.size === 0) {
    emptyEl.style.display = "flex";
    resultsEl.style.display = "none";
    return;
  }

  emptyEl.style.display = "none";
  resultsEl.style.display = "block";

  document.getElementById("summary-bar").textContent =
    `${taken.size} courses \u00b7 ${credits.toFixed(1)} credits \u00b7 ${progResults.length} program(s)`;

  renderGE(geResult);
  renderPrograms(progResults, pwResults);
  renderSuggestedPlan(selectedProgs, taken, geResult);
  renderF2Y(selectedProgs, taken);
  renderTrajectory(selectedProgs, taken);
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

function renderSuggestedPlan(selectedProgs, taken, geResult) {
  const el = document.getElementById("plan-content");
  if (selectedProgs.length === 0) {
    el.innerHTML = '<div class="empty">Select a major to see suggested plan</div>';
    return;
  }
  const { semBuckets } = buildSuggestedPlan(selectedProgs, taken, geResult);
  let html = "";
  for (let sem = 1; sem <= 8; sem++) {
    const items = semBuckets[sem];
    if (items.length === 0) continue;
    const label = PLAN_SEM_LABELS[sem] || `Semester ${sem}`;
    const doneCount = items.filter(i => i.done).length;
    const totalCount = items.filter(i => !i.isHint).length;
    html += `<div class="plan-section open">
      <div class="plan-section-header" onclick="this.parentElement.classList.toggle('open')">
        <span class="arrow">\u25B6</span>
        ${label}
        <span class="prog-pct">${doneCount}/${totalCount}</span>
      </div>
      <div class="plan-section-body">`;
    for (const item of items) {
      if (item.isHint) {
        html += `<div class="plan-item ge-hint">${item.display}</div>`;
      } else {
        const cls = item.done ? "done" : "todo";
        const icon = item.done ? "\u2713" : "\u25CB";
        let hint = "";
        if (item.pct != null) hint = `${Math.round(item.pct * 100)}% of grads`;
        if (item.trajSem) hint += (hint ? " \u00b7 " : "") + `Sem ${item.trajSem}`;
        html += `<div class="plan-item ${cls}">
          <span class="icon">${icon}</span>
          <span class="label">${item.display}</span>
          ${hint ? `<span class="hint">${hint}</span>` : ""}
        </div>`;
      }
    }
    html += `</div></div>`;
  }
  el.innerHTML = html || '<div class="empty">No plan data available</div>';
}

function renderF2Y(selectedProgs, taken) {
  const el = document.getElementById("f2y-content");
  const entries = findF2YEntries(selectedProgs);
  if (entries.length === 0) {
    el.innerHTML = '<div class="empty">No first-two-years data for selected programs</div>';
    return;
  }
  let html = "";
  for (const entry of entries) {
    html += `<div class="prog-card open">
      <div class="prog-header" onclick="this.parentElement.classList.toggle('open')">
        <span class="arrow">\u25B6</span>
        <strong>${entry.label}</strong>
      </div>
      <div class="prog-body">`;
    if (entry.variant_note) html += `<div class="plan-note">${entry.variant_note}</div>`;
    const semKeys = ["y1_fall", "y1_spring", "y2_fall", "y2_spring"];
    const semLabels = { y1_fall: "Year 1 \u2014 Fall", y1_spring: "Year 1 \u2014 Spring",
                        y2_fall: "Year 2 \u2014 Fall", y2_spring: "Year 2 \u2014 Spring" };
    for (const key of semKeys) {
      const sd = (entry.semesters || {})[key];
      if (!sd) continue;
      html += `<div style="margin-top:8px"><strong style="font-size:12px;color:#8b1a1a">${semLabels[key]}</strong></div>`;
      for (const cat of ["essential", "suggested"]) {
        for (const item of (sd[cat] || [])) {
          const code = normalize(item);
          const isCode = /^[A-Z]+-\d/.test(code);
          const done = isCode && taken.has(code);
          const cls = done ? "done" : "todo";
          const icon = done ? "\u2713" : "\u25CB";
          const catLabel = cat === "essential" ? "" : " (suggested)";
          html += `<div class="plan-item ${cls}">
            <span class="icon">${icon}</span>
            <span class="label">${item}${catLabel}</span>
          </div>`;
        }
      }
    }
    if (entry.notes) html += `<div class="plan-note">${entry.notes}</div>`;
    html += `</div></div>`;
  }
  el.innerHTML = html;
}

function renderTrajectory(selectedProgs, taken) {
  const el = document.getElementById("trajectory-content");
  const majorCode = findMajorCode(selectedProgs);
  if (!majorCode) {
    el.innerHTML = '<div class="empty">Select a major to see trajectory data</div>';
    return;
  }
  const suggestions = electiveSuggestions(majorCode, taken);
  if (suggestions.length === 0) {
    el.innerHTML = '<div class="empty">No trajectory suggestions available</div>';
    return;
  }
  let html = `<p style="font-size:12px;color:#64748b;margin-bottom:8px">
    Common courses taken by ${majorCode} graduates (not already in your list):</p>`;
  for (const [code, info] of suggestions) {
    const pct = Math.round(info.pct * 100);
    const sem = info.sem ? `Sem ${info.sem}` : "";
    html += `<div class="plan-item todo">
      <span class="icon">\u25CB</span>
      <span class="label">${code}</span>
      <span class="hint">${pct}% of grads${sem ? " \u00b7 " + sem : ""}</span>
    </div>`;
  }
  el.innerHTML = html;
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
  if (matchedRoute.pathway) {
    document.querySelectorAll(".pw-check input").forEach(cb => {
      if (cb.value === matchedRoute.pathway) cb.checked = true;
    });
  }

  // Pre-populate first semester courses
  if (matchedRoute.semester_1 && matchedRoute.semester_1.length > 0) {
    const semContainer = document.getElementById("semesters");
    semContainer.innerHTML = "";
    addSemester("Semester 1", matchedRoute.semester_1.join("\n"));
    for (let i = 2; i <= 4; i++) addSemester(`Semester ${i}`, "");
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

// ─── Semester management ─────────────────────────────────────────────────────

function addSemester(label, courses, completed) {
  label = label || `Semester ${document.querySelectorAll(".semester").length + 1}`;
  courses = courses || "";
  if (completed === undefined) completed = false;
  const container = document.getElementById("semesters");
  const div = document.createElement("div");
  div.className = "semester open";
  const checkedAttr = completed ? " checked" : "";
  div.innerHTML = `<div class="sem-header" onclick="toggleSem(event, this)">
    <span class="arrow">\u25B6</span>
    <span class="sem-label">${label}</span>
    <label class="sem-status" onclick="event.stopPropagation()">
      <input type="checkbox"${checkedAttr}> Completed
    </label>
    <button class="small-btn remove-sem" onclick="event.stopPropagation(); this.closest('.semester').remove()" title="Remove">\u00d7</button>
  </div>
  <div class="sem-body">
    <textarea class="sem-courses" rows="3" placeholder="One course per line: BIO-145, CHM 121...">${courses}</textarea>
  </div>`;
  container.appendChild(div);
  // Collapse if it has courses (loaded from file) — keep new empty ones open
  if (courses && completed) {
    div.classList.remove("open");
  }
}

function toggleSem(e, header) {
  if (e.target.closest(".sem-status") || e.target.closest(".remove-sem")) return;
  header.closest(".semester").classList.toggle("open");
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

  // Populate pathways
  const pwContainer = document.getElementById("pathways");
  for (const [id, pw] of Object.entries(DATA.pathways || {})) {
    const label = document.createElement("label");
    label.className = "pw-check";
    label.innerHTML = `<input type="checkbox" value="${id}"> ${pw.name || id}`;
    pwContainer.appendChild(label);
  }

  // Transfer WE
  const weSel = document.getElementById("transfer-we");
  const weOpts = ["0 credits (5 WE)", "1\u20137 credits (5 WE)",
                  "8\u201315 credits (3 WE)", "16+ credits (2 WE)"];
  for (const w of weOpts) {
    const opt = document.createElement("option");
    opt.value = w; opt.textContent = w;
    weSel.appendChild(opt);
  }

  // Default semesters
  addSemester("Transfer", "");
  for (let i = 1; i <= 4; i++) addSemester(`Semester ${i}`, "");

  // Show/hide pathways when major selection changes
  function updatePathwaysVisibility() {
    const hasMajor = [1,2,3].some(i => document.getElementById(`major${i}`).value);
    document.getElementById("pathways-row").style.display = hasMajor ? "" : "none";
  }
  for (let i = 1; i <= 3; i++) {
    document.getElementById(`major${i}`).addEventListener("change", updatePathwaysVisibility);
  }

  // Auto-check on changes
  document.getElementById("input-panel").addEventListener("change", () => runCheck());
  document.getElementById("input-panel").addEventListener("input", debounce(runCheck, 500));

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
}

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

document.addEventListener("DOMContentLoaded", init);
