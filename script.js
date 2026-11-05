
const API_URL = "http://127.0.0.1:5000";

// ==========================================
// HTML ELEMENTS
// ==========================================

const searchInput = document.getElementById("searchInput");
const categoryFilter = document.getElementById("categoryFilter");
const qualificationFilter = document.getElementById("qualificationFilter");
const examList = document.getElementById("examList");
const noResults = document.getElementById("noResults");
const sscNotices = document.getElementById("sscNotices");

let exams = [];
let latestSSCNotices = [];
let apiLastUpdated = "";

// ==========================================
// DETERMINE QUALIFICATION LEVELS
// ==========================================

function getQualificationLevels(qualification) {
    const text = (qualification || "").toLowerCase();
    const levels = [];

    if (text.includes("10th") || text.includes("matriculation")) {
        levels.push("10th");
    }

    if (text.includes("12th") || text.includes("intermediate")) {
        levels.push("12th");
    }

    if (
        text.includes("bachelor") ||
        text.includes("graduate") ||
        text.includes("graduation") ||
        text.includes("master") ||
        text.includes("engineering degree") ||
        text.includes("professional degree") ||
        text.includes("teacher-training") ||
        text.includes("d.el.ed") ||
        text.includes("b.ed") ||
        text.includes("relevant diploma")
    ) {
        levels.push("Graduate");
    }

    return [...new Set(levels)];
}

// ==========================================
// LOAD EXAMS
// ==========================================

async function loadExams() {
    try {
        examList.innerHTML = "<p>Loading government exams...</p>";

        const response = await fetch(`${API_URL}/api/exams`);

        if (!response.ok) {
            throw new Error("API request failed: " + response.status);
        }

        const data = await response.json();

        exams = Array.isArray(data) ? data : data.exams;

        // Get the API-level update time.
        apiLastUpdated = data.last_updated || "";

        if (!Array.isArray(exams)) {
            throw new Error("Invalid exam data received from backend.");
        }

        updateStatistics(exams);
        displayExams(exams);

        console.log("Exams loaded successfully:", exams.length);
        console.log("API last updated:", apiLastUpdated);

    } catch (error) {
        console.error("Exam loading error:", error);

        examList.textContent =
            "Unable to load exams: " + error.message;

        if (noResults) {
            noResults.hidden = true;
        }
    }
}

// ==========================================
// UPDATE STATISTICS
// ==========================================

function updateStatistics(examData) {
    const examCount = document.getElementById("examCount");
    const categoryCount = document.getElementById("categoryCount");
    const calendarCount = document.getElementById("calendarCount");

    if (examCount) {
        examCount.textContent = examData.length;
    }

    const categories = new Set(
        examData.map(exam => exam.category).filter(Boolean)
    );

    if (categoryCount) {
        categoryCount.textContent = categories.size;
    }

    const calendars = new Set(
        examData.map(exam => exam.official_calendar).filter(Boolean)
    );

    if (calendarCount) {
        calendarCount.textContent = calendars.size;
    }
}

// ==========================================
// DISPLAY EXAM CARDS
// ==========================================

function displayExams(examData) {
    examList.innerHTML = "";

    examData.forEach(function (exam) {
        const card = document.createElement("div");

        card.className = "exam";
        card.dataset.category = exam.category || "";

        const qualificationLevels =
            getQualificationLevels(exam.qualification);

        card.dataset.qualification =
            qualificationLevels.join(",");

        card.innerHTML = `
            <h3></h3>
            <div class="exam-status"></div>
            <p class="category"></p>
            <p class="qualification"></p>
            <p class="exam-date"></p>
            <p class="last-date"></p>
            <p class="last-checked"></p>
            <div class="calendar-link"></div>
            <div class="latest-exam-notice"></div>
            <p class="eligibility"></p>
            <div class="official-link"></div>

            <button class="details-btn" type="button">
                View Details
            </button>

            <div class="details" hidden>
                <p>
                    For confirmed dates and eligibility,
                    refer to the official notification.
                </p>
                <div class="calendar-details"></div>
                <div class="notice-details"></div>
                <div class="eligibility-details"></div>
            </div>
        `;

        card.querySelector("h3").textContent =
            exam.name || "Unnamed Exam";

        // ==========================================
        // EXAM STATUS
        // ==========================================

        const statusContainer =
            card.querySelector(".exam-status");

        const statusFields = [
            ["Application", exam.application_status],
            ["Exam", exam.exam_status]
        ];

        statusFields.forEach(function (field) {
            if (field[1]) {
                const badge = document.createElement("span");

                badge.className = "status-badge";
                badge.textContent = field[0] + ": " + field[1];

                statusContainer.appendChild(badge);
            }
        });

        // ==========================================
        // BASIC EXAM INFORMATION
        // ==========================================

        card.querySelector(".category").textContent =
            "Category: " + (exam.category || "Not specified");

        card.querySelector(".qualification").textContent =
            "Qualification: " +
            (exam.qualification || "Check notification");

        card.querySelector(".exam-date").textContent =
            "Exam date: " + (exam.exam_date || "Not announced");

        card.querySelector(".last-date").textContent =
            "Last date to apply: " +
            (exam.last_date_to_apply || "Not announced");

        // Use individual exam timestamp first.
        // For UPSC, fall back to the API-level timestamp.
        const lastChecked =
            exam.last_updated ||
            exam.last_checked ||
            (
                exam.name === "UPSC Civil Services"
                    ? apiLastUpdated
                    : ""
            );

        card.querySelector(".last-checked").textContent =
            "Last checked: " + (lastChecked || "Not checked");

        card.querySelector(".eligibility").textContent =
            "Eligibility: " +
            (exam.eligibility || "Check official notification");

        // ==========================================
        // OFFICIAL CALENDAR LINK
        // ==========================================

        if (exam.official_calendar) {
            const calendarLink = document.createElement("a");

            calendarLink.href = exam.official_calendar;
            calendarLink.target = "_blank";
            calendarLink.rel = "noopener noreferrer";

            calendarLink.textContent =
              exam.name === "SSC CGL"
              ? "View SSC Tentative Calendar 2026-27"
              : "View Official Exam Calendar";

            card.querySelector(".calendar-link")
                .appendChild(calendarLink);

            card.querySelector(".calendar-details")
                .appendChild(calendarLink.cloneNode(true));
        }

        // ==========================================
        // LATEST SSC NOTICE ON SSC CGL
        // ==========================================

        if ((exam.name || "").toLowerCase() === "ssc cgl") {
            const noticeContainer =
                card.querySelector(".latest-exam-notice");

            const detailsNotice =
                card.querySelector(".notice-details");

            if (latestSSCNotices.length > 0) {
                const notice = latestSSCNotices[0];

                const noticeTitle = document.createElement("p");

                noticeTitle.textContent =
                "Latest regional notice: " + notice.title;

                const noticeDescription = document.createElement("p");

                noticeDescription.textContent =
                 "For candidates affected by exam-city reassignment.";

                const noticeLink = document.createElement("a");

                noticeLink.href = notice.url;
                noticeLink.target = "_blank";
                noticeLink.rel = "noopener noreferrer";
                noticeLink.textContent = "Open Latest SSC Notice";

                noticeContainer.appendChild(noticeTitle);
                noticeContainer.appendChild(noticeDescription);
                noticeContainer.appendChild(noticeLink);

                detailsNotice.appendChild(noticeLink.cloneNode(true));

            } else {
                noticeContainer.textContent =
                    "Latest SSC notice unavailable. Check the official website.";
            }
        }

        // ==========================================
        // OFFICIAL WEBSITE LINK
        // ==========================================

        if (exam.official_website) {
            const officialLink = document.createElement("a");

            officialLink.href = exam.official_website;
            officialLink.target = "_blank";
            officialLink.rel = "noopener noreferrer";

            officialLink.textContent = "Official Website";

            card.querySelector(".official-link")
                .appendChild(officialLink);
        }

        // ==========================================
        // ELIGIBILITY DETAILS
        // ==========================================

        const eligibilityDetails =
            card.querySelector(".eligibility-details");

        const detailFields = [
            ["Age Limit", exam.age_limit],
            ["Age Relaxation", exam.age_relaxation],
            ["Physical Requirements", exam.physical_requirements]
        ];

        detailFields.forEach(function (field) {
            if (field[1]) {
                const paragraph = document.createElement("p");

                paragraph.textContent =
                    field[0] + ": " + field[1];

                eligibilityDetails.appendChild(paragraph);
            }
        });

        if (exam.eligibility_source) {
            const sourceLink = document.createElement("a");

            sourceLink.href = exam.eligibility_source;
            sourceLink.target = "_blank";
            sourceLink.rel = "noopener noreferrer";

            sourceLink.textContent =
                "View Official Eligibility Notification";

            eligibilityDetails.appendChild(sourceLink);
        }

        if (exam.eligibility_checked) {
            const checked = document.createElement("p");

            checked.textContent =
                "Eligibility last checked: " +
                exam.eligibility_checked;

            eligibilityDetails.appendChild(checked);
        }

        // ==========================================
        // VIEW DETAILS BUTTON
        // ==========================================

        const button = card.querySelector(".details-btn");
        const details = card.querySelector(".details");

        button.addEventListener("click", function () {
            details.hidden = !details.hidden;

            button.textContent = details.hidden
                ? "View Details"
                : "Hide Details";
        });

        examList.appendChild(card);
    });

    filterExams();
}

// ==========================================
// SEARCH AND FILTER
// ==========================================

function filterExams() {
    if (
        !searchInput ||
        !categoryFilter ||
        !qualificationFilter ||
        !noResults
    ) {
        console.error("Search or filter HTML elements are missing.");
        return;
    }

    const searchText =
        searchInput.value.toLowerCase().trim();

    const selectedCategory = categoryFilter.value;
    const selectedQualification = qualificationFilter.value;

    let visibleCount = 0;

    examList.querySelectorAll(".exam").forEach(function (card) {
        const matchesSearch =
            card.innerText.toLowerCase().includes(searchText);

        const matchesCategory =
            selectedCategory === "All" ||
            card.dataset.category === selectedCategory;

        const availableQualifications =
            card.dataset.qualification.split(",");

        const matchesQualification =
            selectedQualification === "All" ||
            availableQualifications.includes(selectedQualification);

        const showExam =
            matchesSearch &&
            matchesCategory &&
            matchesQualification;

        card.style.display = showExam ? "" : "none";

        if (showExam) {
            visibleCount++;
        }
    });

    noResults.hidden = visibleCount > 0;
}

// ==========================================
// FILTER EVENT LISTENERS
// ==========================================

if (searchInput) {
    searchInput.addEventListener("input", filterExams);
}

if (categoryFilter) {
    categoryFilter.addEventListener("change", filterExams);
}

if (qualificationFilter) {
    qualificationFilter.addEventListener("change", filterExams);
}

// ==========================================
// LOAD SSC NOTICES
// ==========================================

async function loadSSCNotices() {
    if (!sscNotices) {
        console.error("SSC notices HTML element is missing.");
        return;
    }

    sscNotices.textContent = "Loading official notices...";

    try {
        const response =
            await fetch(`${API_URL}/api/ssc-notices`);

        if (!response.ok) {
            throw new Error("Unable to fetch SSC notices");
        }

        const data = await response.json();

        latestSSCNotices = Array.isArray(data.notices)
            ? data.notices
            : [];

        sscNotices.innerHTML = "";

        const checkedTime = document.createElement("p");

        checkedTime.textContent =
            "Last checked: " + (data.checked_at || "Unknown");

        sscNotices.appendChild(checkedTime);

        // ==========================================
        // DISPLAY NOTICES
        // ==========================================

        if (latestSSCNotices.length === 0) {
            const message = document.createElement("p");

            message.textContent =
                "No matching notices found. Check the official SSC website.";

            sscNotices.appendChild(message);

        } else {
            latestSSCNotices.forEach(function (notice) {
                const noticeCard = document.createElement("div");
                noticeCard.className = "notice-card";

                const title = document.createElement("h3");
                title.textContent = notice.title || "SSC Notice";

                const link = document.createElement("a");

                if (notice.url) {
                    link.href = notice.url;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.textContent = "Open Official Notice";
                }

                noticeCard.appendChild(title);

                if (notice.url) {
                    noticeCard.appendChild(link);
                }

                sscNotices.appendChild(noticeCard);
            });
        }

        // ==========================================
        // OFFICIAL SSC SOURCE LINKS
        // ==========================================

        const sourceText = document.createElement("p");

        sourceText.appendChild(
            document.createTextNode("Official sources: ")
        );

        const sources = Array.isArray(data.source)
            ? data.source
            : [];

        sources.forEach(function (url, index) {
            if (index > 0) {
                sourceText.appendChild(
                    document.createTextNode(" | ")
                );
            }

            const sourceLink = document.createElement("a");

            sourceLink.href = url;
            sourceLink.target = "_blank";
            sourceLink.rel = "noopener noreferrer";

            sourceLink.textContent =
                index === 0
                    ? "SSC Main Website"
                    : "SSC Regional Notices";

            sourceText.appendChild(sourceLink);
        });

        sscNotices.appendChild(sourceText);

        // Refresh exam cards with latest SSC notice.
        if (exams.length > 0) {
            displayExams(exams);
        }

        console.log("SSC notices loaded successfully.");

    } catch (error) {
        sscNotices.textContent =
            "Unable to load notices. Please check that Flask is running.";

        console.error("Error loading SSC notices:", error);
    }
}

// ==========================================
// START APPLICATION
// ==========================================

loadExams();
loadSSCNotices();
