import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One section of Settings: its title with its actions beside it, then its settings in a column that scrolls.
// `goTo` asks the dialog for another section.
Item {
    id: page

    property string title
    property string lead: ""
    property alias actions: actionRow.data
    default property alias content: body.data

    signal goTo(string key)

    Flickable {
        id: flick

        anchors.fill: parent
        contentHeight: column.implicitHeight + 2 * Theme.space_2xl
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: column

            x: Theme.space_2xl + Theme.space_md
            y: Theme.space_2xl
            width: flick.width - 2 * (Theme.space_2xl + Theme.space_md)
            spacing: Theme.space_md

            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: Theme.space_sm
                spacing: Theme.space_md

                UiText {
                    Layout.fillWidth: true
                    text: page.title
                    font.pixelSize: Theme.text_xl
                    font.weight: Font.Bold
                    Accessible.role: Accessible.Heading
                }

                RowLayout {
                    id: actionRow

                    spacing: Theme.space_sm
                }
            }

            Hint {
                text: page.lead
                font.pixelSize: Theme.text_md
            }

            ColumnLayout {
                id: body

                Layout.fillWidth: true
                spacing: Theme.space_md
            }
        }
    }
}
