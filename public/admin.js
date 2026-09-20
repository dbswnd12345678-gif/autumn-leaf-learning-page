const adminKeyInput = document.getElementById("admin-key");
const loadBtn = document.getElementById("load-btn");
const sessionTbody = document.getElementById("session-tbody");
const downloadAllXlsxBtn = document.getElementById("download-all-xlsx");
const downloadAllDocxBtn = document.getElementById("download-all-docx");

// 페이지를 새로고침해도 매번 키를 다시 입력하지 않도록 이 브라우저(내 PC)에만 저장한다.
const savedKey = localStorage.getItem("autumn_leaf_admin_key");
if (savedKey) adminKeyInput.value = savedKey;

function getKey() {
  return adminKeyInput.value.trim();
}

function showStatus(message) {
  let el = document.getElementById("status-msg");
  if (!el) {
    el = document.createElement("p");
    el.id = "status-msg";
    document.querySelector(".key-box").appendChild(el);
  }
  el.textContent = message || "";
}

async function loadSessions() {
  const key = getKey();
  if (!key) {
    showStatus("관리자 키를 입력해주세요.");
    return;
  }
  localStorage.setItem("autumn_leaf_admin_key", key);
  showStatus("불러오는 중...");

  try {
    const res = await fetch(`/api/admin/sessions?key=${encodeURIComponent(key)}`);
    const data = await res.json();
    if (!res.ok) {
      showStatus(data.error || "불러오기에 실패했습니다.");
      sessionTbody.innerHTML = `<tr><td colspan="6" class="empty">불러오기에 실패했습니다.</td></tr>`;
      return;
    }

    showStatus("");
    if (!data.students || data.students.length === 0) {
      sessionTbody.innerHTML = `<tr><td colspan="6" class="empty">아직 저장된 대화 기록이 없습니다.</td></tr>`;
      return;
    }

    sessionTbody.innerHTML = "";
    data.students.forEach((student) => {
      const tr = document.createElement("tr");

      const tdId = document.createElement("td");
      tdId.textContent = student.student_id;

      const tdCount = document.createElement("td");
      tdCount.textContent = student.turn_count;

      const tdSessionCount = document.createElement("td");
      tdSessionCount.textContent = student.session_count;

      const tdFirst = document.createElement("td");
      tdFirst.textContent = student.first_at || "-";

      const tdLast = document.createElement("td");
      tdLast.textContent = student.last_at || "-";

      const tdActions = document.createElement("td");
      const xlsxLink = document.createElement("a");
      xlsxLink.href = `/api/history/${encodeURIComponent(student.student_id)}/export?format=xlsx`;
      xlsxLink.textContent = "엑셀";
      xlsxLink.style.marginRight = "8px";

      const docxLink = document.createElement("a");
      docxLink.href = `/api/history/${encodeURIComponent(student.student_id)}/export?format=docx`;
      docxLink.textContent = "워드";

      tdActions.appendChild(xlsxLink);
      tdActions.appendChild(docxLink);

      tr.appendChild(tdId);
      tr.appendChild(tdCount);
      tr.appendChild(tdSessionCount);
      tr.appendChild(tdFirst);
      tr.appendChild(tdLast);
      tr.appendChild(tdActions);
      sessionTbody.appendChild(tr);
    });
  } catch (err) {
    showStatus("서버에 연결할 수 없습니다.");
  }
}

function downloadAll(format) {
  const key = getKey();
  if (!key) {
    showStatus("관리자 키를 입력해주세요.");
    return;
  }
  localStorage.setItem("autumn_leaf_admin_key", key);
  window.location.href = `/api/admin/export?key=${encodeURIComponent(key)}&format=${format}`;
}

loadBtn.addEventListener("click", loadSessions);
downloadAllXlsxBtn.addEventListener("click", () => downloadAll("xlsx"));
downloadAllDocxBtn.addEventListener("click", () => downloadAll("docx"));

if (savedKey) {
  loadSessions();
}