#include <LiquidCrystal.h>

LiquidCrystal lcd(12, 11, 5, 4, 3, 2);

void setup() {
  Serial.begin(9600);

  lcd.begin(16, 2);
  lcd.print("Paper Plane");
  lcd.setCursor(0, 1);
  lcd.print("Waiting...");
}

void loop() {
  if (Serial.available()) {
    String message = Serial.readStringUntil('\n');
    message.trim();

    if (message.startsWith("SCORE:")) {
      int score = message.substring(6).toInt();

      lcd.clear();
      lcd.print("Flight Score:");
      lcd.setCursor(0, 1);
      lcd.print(score);
    }
  }
}
