import QtQuick
import QtQuick.Layouts
import Showrunner

// The app name, the profile pill, the search field in the middle, the drawer and settings buttons, the change
// count and the way to Review.
Item {
    id: bar

    property bool drawerOpen: false
    property alias search: search

    signal drawerToggled()

    implicitHeight: Theme.top_bar

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.space_lg + Theme.space_xs
        anchors.rightMargin: Theme.space_md + Theme.space_xs
        spacing: Theme.space_lg

        Row {
            spacing: Theme.space_md

            Image {
                anchors.verticalCenter: parent.verticalCenter
                width: Theme.icon_lg
                height: Theme.icon_lg
                sourceSize: Qt.size(Theme.icon_lg, Theme.icon_lg)
                source: "image://icon/logo/" + Theme.ink.toString().substring(1, 7) + "/"
                        + Theme.control.toString().substring(1, 7)
                Accessible.ignored: true
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                text: Strings.t("app.name")
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
            }
        }

        ProfilePill {}

        Item {
            Layout.fillWidth: true
        }

        Item {
            Layout.fillWidth: true
        }

        IconButton {
            iconName: "panel_bottom"
            label: Strings.t("top.drawer")
            active: bar.drawerOpen
            onClicked: bar.drawerToggled()
        }

        IconButton {
            iconName: "sliders"
            label: Strings.t("top.settings")
            enabled: false
        }

        UiText {
            text: app.change_count > 0 ? Strings.n("top.changes", app.change_count) : Strings.t("top.nothing")
            color: Theme.muted
            font.pixelSize: Theme.text_md
        }

        ActionButton {
            text: app.change_count > 0 ? Strings.t("top.review_apply") : Strings.t("top.review")
            kind: app.change_count > 0 ? "primary" : "outline"
            iconName: app.change_count > 0 ? "arrow" : ""
            // Review and Apply come with the Review place.
            enabled: false
        }
    }

    FindField {
        id: search

        anchors.centerIn: parent
        width: Theme.search_width
        placeholderText: Strings.t("top.search")
        hint: Strings.t("top.search_key")
        text: app.filter_text
        onTextEdited: app.filter_text = text
    }
}
