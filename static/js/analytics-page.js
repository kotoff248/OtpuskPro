document.addEventListener("DOMContentLoaded", function () {
    const chartOne = document.getElementById("chart1");
    const chartTwo = document.getElementById("chart2");
    const chartThree = document.getElementById("chart3");

    if (!chartOne || !chartTwo || !chartThree || typeof Chart === "undefined") {
        return;
    }

    const values1 = JSON.parse(document.getElementById("analytics-values1").textContent || "[]");
    const values2 = JSON.parse(document.getElementById("analytics-values2").textContent || "[]");
    const values3 = JSON.parse(document.getElementById("analytics-values3").textContent || "[]");

    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            tooltip: {
                callbacks: {
                    label: function (context) {
                        return context.raw;
                    }
                },
                backgroundColor: "rgba(0, 0, 0, 0.7)",
                titleColor: "#fff",
                bodyColor: "#fff",
                borderColor: "#ddd",
                borderWidth: 1
            },
            legend: {
                labels: {
                    color: "#fff",
                    font: {
                        size: 16,
                        family: "'Poppins', sans-serif"
                    }
                }
            }
        },
        layout: {
            padding: {
                top: 20
            }
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: {
                    color: "rgba(200, 200, 200, 0.2)"
                },
                ticks: {
                    color: "#fff"
                }
            },
            x: {
                grid: {
                    color: "rgba(200, 200, 200, 0.08)"
                },
                ticks: {
                    color: "#fff"
                }
            }
        }
    };

    const labels = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

    const charts = [
        new Chart(chartOne.getContext("2d"), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Количество отпусков",
                    data: values1,
                    backgroundColor: "rgba(0, 175, 245, 0.7)",
                    borderColor: "#00aff5",
                    borderWidth: 2,
                    hoverBackgroundColor: "rgba(0, 175, 245, 0.9)"
                }]
            },
            options: commonOptions
        }),
        new Chart(chartTwo.getContext("2d"), {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Средняя продолжительность (дни)",
                    data: values2,
                    backgroundColor: "rgba(0, 175, 245, 0.2)",
                    borderColor: "#00aff5",
                    borderWidth: 2,
                    fill: true,
                    pointBackgroundColor: "#00aff5",
                    pointBorderColor: "#00aff5"
                }]
            },
            options: commonOptions
        }),
        new Chart(chartThree.getContext("2d"), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Запланированные отпуска (дни)",
                    data: values3,
                    backgroundColor: "rgba(0, 175, 245, 0.7)",
                    borderColor: "#00aff5",
                    borderWidth: 2,
                    hoverBackgroundColor: "rgba(0, 175, 245, 0.9)"
                }]
            },
            options: commonOptions
        })
    ];

    const canvases = charts.map(function (chart) {
        return chart.canvas;
    });
    let currentChartIndex = 0;

    function showChart(index) {
        canvases.forEach(function (canvas, canvasIndex) {
            const isActive = canvasIndex === index;
            canvas.classList.toggle("is-hidden", !isActive);
            canvas.style.opacity = isActive ? "1" : "0";
        });
    }

    function moveChart(direction) {
        currentChartIndex = (currentChartIndex + direction + charts.length) % charts.length;
        showChart(currentChartIndex);
    }

    document.getElementById("prev").addEventListener("click", function () {
        moveChart(-1);
    });

    document.getElementById("next").addEventListener("click", function () {
        moveChart(1);
    });

    showChart(currentChartIndex);

    document.querySelectorAll(".progress[data-progress]").forEach(function (circle) {
        const percentage = Number(circle.dataset.progress || 0);
        const radius = circle.r.baseVal.value;
        const circumference = 2 * Math.PI * radius;
        const offset = circumference - (percentage / 100) * circumference;
        circle.style.strokeDasharray = circumference + " " + circumference;
        circle.style.strokeDashoffset = offset;
    });
});
