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

    onPlaceChanged: tab = tabs.length > 0 ? tabs[0].key : ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.stroke
        spacing: 0

        Tabs {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space_sm
            model: side.tabs.map(entry => Object.assign({}, entry, {
                label: Strings.t("panel.tab." + entry.key),
                change: false
            }))
            current: side.tab
            onPicked: key => side.tab = key
        }

        Placeholder {
            Layout.fillWidth: true
            Layout.fillHeight: true
            title: side.tab !== "" ? Strings.t("panel.placeholder." + side.tab + ".title") : ""
            lead: side.tab !== "" ? Strings.t("panel.placeholder." + side.tab + ".lead") : ""
        }
    }
}
