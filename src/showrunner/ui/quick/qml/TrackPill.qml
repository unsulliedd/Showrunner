import QtQuick
import Showrunner

// One track of one file in an episode row: its code, struck when dropped and dashed mint when a paired file is added.
// The default flag colours the code and the forced flag frames it, both in colours Appearance sets; hovering says so.
Item {
    id: pill

    required property var track
    readonly property string flagsTip: pill.track.default && pill.track.forced ? Strings.t("tracks.flags_tip.both")
        : pill.track.default ? Strings.t("tracks.flags_tip.default")
        : pill.track.forced ? Strings.t("tracks.flags_tip.forced") : ""

    implicitWidth: row.implicitWidth + 2 * Theme.space_sm
    implicitHeight: Theme.pill
    Accessible.role: Accessible.StaticText
    Accessible.name: pill.flagsTip === "" ? pill.track.code : pill.track.code + " " + pill.flagsTip

    Rectangle {
        anchors.fill: parent
        visible: !pill.track.added
        radius: Theme.radius_sm
        color: pill.track.state === "dropped" ? "transparent" : Theme.panel_3
        border.width: pill.track.forced ? Theme.stroke : 0
        border.color: Theme.flag_forced
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
            color: pill.track.state === "dropped" ? Theme.drop : pill.track.added ? Theme.add
                 : pill.track.default ? Theme.flag_default : Theme.ink
            font.pixelSize: Theme.text_xs
            font.weight: Font.DemiBold
            font.strikeout: pill.track.state === "dropped"
        }
    }

    HoverHandler {
        id: hover
    }

    Tip {
        visible: hover.hovered && pill.flagsTip !== ""
        text: pill.flagsTip
    }
}
