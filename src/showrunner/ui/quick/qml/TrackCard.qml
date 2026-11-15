import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One track of a movie: star and F set the flags, x drops it, Restore undoes every choice on it. A paired file
// not yet added is a dashed card that adds it.
Item {
    id: card

    required property var track
    readonly property bool dropped: track.state === "dropped"
    readonly property bool offered: track.state === "paired"

    implicitHeight: Theme.track_card

    Rectangle {
        anchors.fill: parent
        visible: !card.offered
        radius: Theme.radius_lg
        color: card.dropped ? Theme.drop_soft : Theme.panel_2
        border.width: Theme.stroke
        border.color: card.dropped ? Theme.drop : card.track.state === "added" ? Theme.add : Theme.line
    }

    DashedFrame {
        anchors.fill: parent
        visible: card.offered
        radius: Theme.radius_lg
        stroke: Theme.line_strong
    }

    ActionButton {
        anchors.fill: parent
        visible: card.offered
        kind: "ghost"
        iconName: "plus"
        text: Strings.f("movie.add_paired", {"title": card.track.title, "code": card.track.code})
        onClicked: app.toggle_keep(card.track.id)
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.space_lg
        anchors.rightMargin: Theme.space_md
        visible: !card.offered
        spacing: Theme.space_lg

        CodeBadge {
            code: card.track.code
            look: card.track.state
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.space_xs

            UiText {
                Layout.fillWidth: true
                text: card.track.title
                color: card.dropped ? Theme.drop : Theme.ink
                font.weight: Font.DemiBold
                font.strikeout: card.dropped
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space_sm

                Icon {
                    visible: !card.dropped && card.track.name !== ""
                    name: "names"
                    size: Theme.icon_sm
                    color: card.track.renamed ? Theme.change : Theme.faint
                }

                UiText {
                    text: card.track.name
                    color: card.dropped ? Theme.drop : card.track.renamed ? Theme.change : Theme.muted
                    font.pixelSize: Theme.text_sm
                    font.strikeout: card.dropped
                }

                UiText {
                    Layout.fillWidth: true
                    visible: !card.dropped
                    text: card.track.was
                    color: Theme.faint
                    font.pixelSize: Theme.text_xs
                }
            }
        }

        FlagButton {
            visible: !card.dropped
            flag: "default"
            on: card.track.default
            held: card.track.is_default
            onClicked: app.toggle_flag(card.track.id, "default")
        }

        FlagButton {
            visible: !card.dropped
            flag: "forced"
            on: card.track.forced
            held: card.track.is_forced
            onClicked: app.toggle_flag(card.track.id, "forced")
        }

        IconButton {
            visible: !card.dropped
            implicitWidth: Theme.row_sm
            implicitHeight: Theme.row_sm
            iconName: "x"
            label: Strings.t("tracks.drop")
            onClicked: app.toggle_keep(card.track.id)
        }

        ActionButton {
            visible: card.dropped
            text: Strings.t("tracks.restore")
            onClicked: app.restore(card.track.id)
        }
    }
}
