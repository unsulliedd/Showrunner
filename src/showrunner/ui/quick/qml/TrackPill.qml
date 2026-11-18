import QtQuick
import Showrunner

// One track of one file in an episode row: its code with the D or F it ends with; struck when dropped, dashed
// mint when a paired file is added.
Item {
    id: pill

    required property var track

    implicitWidth: row.implicitWidth + 2 * Theme.space_sm
    implicitHeight: Theme.pill

    Rectangle {
        anchors.fill: parent
        visible: !pill.track.added
        radius: Theme.radius_sm
        color: pill.track.state === "dropped" ? "transparent" : Theme.panel_3
    }

    DashedFrame {
        anchors.fill: parent
        visible: pill.track.added
        radius: Theme.radius_sm
        stroke: Theme.add
    }

    Row {
        id: row

        anchors.centerIn: parent
        spacing: Theme.space_xs

        UiText {
            anchors.verticalCenter: parent.verticalCenter
            visible: pill.track.added
            text: Strings.t("tracks.added_mark")
            color: Theme.add
            font.pixelSize: Theme.text_xs
        }

        UiText {
            anchors.verticalCenter: parent.verticalCenter
            mono: true
            text: pill.track.code
            color: pill.track.state === "dropped" ? Theme.drop : pill.track.added ? Theme.add : Theme.ink
            font.pixelSize: Theme.text_xs
            font.weight: Font.DemiBold
            font.strikeout: pill.track.state === "dropped"
        }

        UiText {
            anchors.verticalCenter: parent.verticalCenter
            visible: pill.track.default
            text: Strings.t("tracks.default_mark")
            color: Theme.muted
            font.pixelSize: Theme.text_xs
            font.weight: Font.Bold
        }

        UiText {
            anchors.verticalCenter: parent.verticalCenter
            visible: pill.track.forced
            text: Strings.t("tracks.forced_mark")
            color: Theme.muted
            font.pixelSize: Theme.text_xs
            font.weight: Font.Bold
        }
    }
}
