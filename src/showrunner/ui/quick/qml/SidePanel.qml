import QtQuick
import QtQuick.Layouts
import Showrunner

// The companion panel of a place: its tabs come from the workspace's current place.
Panel {
    id: side

    property string place: "overview"
    readonly property var tabs: {
        app.selected  // the counts belong to the selected video
        return app.side_tabs(place)
    }
    property string tab: tabs.length > 0 ? tabs[0].key : ""

    // Read the new place's tabs here: `tabs` may not have followed the place yet when this handler runs.
    onPlaceChanged: {
        const first = app.side_tabs(place)
        tab = first.length > 0 ? first[0].key : ""
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.stroke
        spacing: 0

        Tabs {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space_sm
            model: side.tabs.map(entry => Object.assign({}, entry, {
                label: Strings.t("panel.tab." + entry.key),
                count: entry.key === "rules" ? app.rules.length : entry.count,
                change: false
            }))
            current: side.tab
            onPicked: key => side.tab = key
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Inspector {
                anchors.fill: parent
                visible: side.tab === "inspector"
            }

            RulesPanel {
                anchors.fill: parent
                visible: side.tab === "rules"
            }

            TokensPanel {
                anchors.fill: parent
                visible: side.tab === "tokens"
            }

            LinesPanel {
                anchors.fill: parent
                visible: side.tab === "lines"
            }

            Placeholder {
                anchors.fill: parent
                visible: side.tab !== "inspector" && side.tab !== "rules" && side.tab !== "tokens" && side.tab !== "lines"
                title: side.tab !== "" ? Strings.t("panel.placeholder." + side.tab + ".title") : ""
                lead: side.tab !== "" ? Strings.t("panel.placeholder." + side.tab + ".lead") : ""
            }
        }
    }
}
