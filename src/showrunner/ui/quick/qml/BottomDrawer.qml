import QtQuick
import QtQuick.Layouts
import Showrunner

// The drawer under the workspace: the player, the jobs, the queue and the log share it.
Panel {
    id: drawer

    property string tab: "jobs"

    signal folded()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.stroke
        spacing: 0

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.drawer_tabs

            Tabs {
                anchors.fill: parent
                anchors.leftMargin: Theme.space_sm
                model: [
                    { key: "player", icon: "play", label: Strings.t("drawer.tab.player") },
                    { key: "jobs", icon: "resume", label: Strings.t("drawer.tab.jobs") },
                    { key: "queue", icon: "list", label: Strings.t("drawer.tab.queue") },
                    { key: "log", icon: "terminal", label: Strings.t("drawer.tab.log") }
                ]
                current: drawer.tab
                onPicked: key => drawer.tab = key
            }

            IconButton {
                anchors.right: parent.right
                anchors.rightMargin: Theme.space_md
                anchors.verticalCenter: parent.verticalCenter
                iconName: "down"
                label: Strings.t("drawer.fold")
                tip: Strings.t("tip.drawer_fold")
                onClicked: drawer.folded()
            }
        }

        JobsPanel {
            id: jobsPanel

            objectName: "jobsPanel"
            Layout.fillWidth: true
            Layout.fillHeight: true
            // Its own copy of the view: each read of `app.jobs.view` converts every file's row.
            visible: drawer.tab === "jobs" && jobsPanel.job.title !== undefined
        }

        QueuePanel {
            id: queuePanel

            objectName: "queuePanel"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: drawer.tab === "queue" && (app.queue.rows.length > 0 || app.queue.note !== "")
        }

        Placeholder {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !jobsPanel.visible && !queuePanel.visible
            title: Strings.t("drawer.placeholder." + drawer.tab + ".title")
            lead: Strings.t("drawer.placeholder." + drawer.tab + ".lead")
        }
    }
}
