plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val syncPythonSources by tasks.registering(Sync::class) {
    from("../../..") {
        include("football_lottery_agent/**/*.py")
    }
    into(layout.buildDirectory.dir("generated/python"))
}

tasks.matching { it.name.endsWith("PythonSources") && it.name != "syncPythonSources" }.configureEach {
    dependsOn(syncPythonSources)
}

android {
    namespace = "com.example.footballlottery"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.footballlottery"
        minSdk = 26
        targetSdk = 35
        versionCode = 15
        versionName = "0.5.1"

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"
    }
    sourceSets {
        getByName("main") {
            srcDir(layout.buildDirectory.dir("generated/python"))
        }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
}
