var driveHandler = new function() {
    //functions used to drive the vehicle. 

    var state = {
        'tele': {
            "user": {
                'angle': 0,
                'throttle': 0,
            },
            "pilot": {
                'angle': 0,
                'throttle': 0,
            }
        },
        'brakeOn': true,
        'recording': false,
        'driveMode': "user",
        'pilot': 'None',
        'session': 'None',
        'lag': 0,
        'controlMode': 'joystick',
        'maxThrottle' : 1,
        'throttleMode' : 'user',
        'num_records': 0,
        'buttons': {
            "w1": false,  // boolean; true is 'down' or pushed, false is 'up' or not pushed
            "w2": false,
            "w3": false,
            "w4": false,
            "w5": false,
        }
    }

    var reviewState = {
        open: false,
        records: [],
        selected: {},  // index -> true
        activeIndex: null,
        loading: false,
        total: 0,
        tubPath: null,
    }

    var joystick_options = {}
    var joystickLoopRunning=false;

    var hasGamepad = false;

    var deviceHasOrientation=false;
    var initialGamma;

    var vehicle_id = ""
    var driveURL = ""
    var socket

    this.load = function() {
      driveURL = '/drive'
      socket = new WebSocket('ws://' + location.host + '/wsDrive');

      setBindings()

      joystick_element = document.getElementById('joystick_container');
      joystick_options = {
        zone: joystick_element,  // active zone
        mode: 'dynamic',
        size: 200,
        color: '#668AED',
        dynamicPage: true,
        follow: true,
      };

      var manager = nipplejs.create(joystick_options);
      bindNipple(manager)

      if(!!navigator.getGamepads){
        console.log("Device has gamepad support.")
        hasGamepad = true;
      }

      if (window.DeviceOrientationEvent) {
        window.addEventListener("deviceorientation", handleOrientation);
        console.log("Browser supports device orientation, setting control mode to tilt.");
        state.controlMode = 'tilt';
        deviceOrientationLoop();
      } else {
        console.log("Device Orientation not supported by browser, setting control mode to joystick.");
        state.controlMode = 'joystick';
      }
    };

    //
    // Update a state object with the given data.
    // This will only update existing fields in 
    // the state; it will not add new fields that
    // may exist in the data but not the state.
    //
    var updateState = function(state, data) {
        let changed = false;
        if(typeof data === 'object') {
            const keys = Object.keys(data)
            keys.forEach(key => {
                //
                // state must already have the key;
                // we are not adding new fields to the state,
                // we are only updating existing fields.
                //
                if(state.hasOwnProperty(key) && state[key] !== data[key]) {
                    if(typeof state[key] === 'object') {
                        // recursively update the state's object field
                        changed = updateState(state[key], data[key]) && changed;
                    } else {
                        state[key] = data[key];
                        changed = true;
                    }
                }
            });
        }
        return changed;
    }

    var setBindings = function() {
      //
      // when server sends a message with state changes
      // then update our local state and 
      // if there were any changes then redraw the UI.
      //
      socket.onmessage = function (event) {
        console.log(event.data);
        const data = JSON.parse(event.data);
        if(updateState(state, data)) {
            updateUI();
        }
      };

      $(document).keydown(function(e) {
          if(e.which == 32) { toggleBrake() }  // 'space'  brake
          if(e.which == 82) { toggleRecording() }  // 'r'  toggle recording
          if(e.which == 73) { throttleUp() }  // 'i'  throttle up
          if(e.which == 75) { throttleDown() } // 'k'  slow down
          if(e.which == 74) { angleLeft() } // 'j' turn left
          if(e.which == 76) { angleRight() } // 'l' turn right
          if(e.which == 65) { updateDriveMode('local') } // 'a' turn on local mode (full _A_uto)
          if(e.which == 85) { updateDriveMode('user') } // 'u' turn on manual mode (_U_user)
          if(e.which == 83) { updateDriveMode('local_angle') } // 's' turn on local mode (auto _S_teering)
          if(e.which == 77) { toggleDriveMode() } // 'm' toggle drive mode (_M_ode)
      });

      $('#mode_select').on('change', function () {
        updateDriveMode($(this).val());
      });

      $('#max_throttle_select').on('change', function () {
        state.maxThrottle = parseFloat($(this).val());
      });

      $('#throttle_mode_select').on('change', function () {
        state.throttleMode = $(this).val();
      });

      $('#record_button').click(function () {
        toggleRecording();
      });

      $('#brake_button').click(function() {
        toggleBrake();
      });

      $('input[type=radio][name=controlMode]').change(function() {
        if (this.value == 'joystick') {
          state.controlMode = "joystick";
          joystickLoopRunning = true;
          console.log('joystick mode');
          joystickLoop();
        } else {
          joystickLoopRunning = false;
        }

        if (deviceHasOrientation && this.value == 'tilt') {
          state.controlMode = "tilt";
          console.log('tilt mode')
        }

        if (hasGamepad && this.value == 'gamepad') {
          state.controlMode = "gamepad";
          console.log('gamepad mode')
          gamePadLoop();
        }
        updateUI();
      });

      // programmable buttons
      $('#button_bar > button').mousedown(function() {
        console.log(`${$(this).attr('id')} mousedown`);
        state.buttons[$(this).attr('id')] = true;
        postDrive(["buttons"]); // write it back to the server
      });
      $('#button_bar > button').mouseup(function() {
        console.log(`${$(this).attr('id')} mouseup`);
        state.buttons[$(this).attr('id')] = false;
        postDrive(["buttons"]); // write it back to the server
      });

      // Review recent recording drawer
      $('#review_button').click(function() {
        openReviewDrawer();
      });
      $('#review_close').click(function() {
        closeReviewDrawer();
      });
      $('#review_refresh').click(function() {
        loadRecentRecords();
      });
      $('#review_n_select').on('change', function() {
        loadRecentRecords();
      });
      $('#review_select_all').click(function() {
        reviewState.records.forEach(function(r) {
          reviewState.selected[r.index] = true;
        });
        renderReviewGrid();
        updateReviewControls();
      });
      $('#review_clear').click(function() {
        reviewState.selected = {};
        renderReviewGrid();
        updateReviewControls();
      });
      $('#review_delete').click(function() {
        deleteSelectedRecords();
      });
    };


    function bindNipple(manager) {
      manager.on('start', function(evt, data) {
        state.tele.user.angle = 0
        state.tele.user.throttle = 0
        state.recording = true
        joystickLoopRunning=true;
        joystickLoop();

      }).on('end', function(evt, data) {
        joystickLoopRunning=false;
        brake()

      }).on('move', function(evt, data) {
        state.brakeOn = false;
        radian = data['angle']['radian']
        distance = data['distance']

        //console.log(data)
        state.tele.user.angle = Math.max(Math.min(Math.cos(radian)/70*distance, 1), -1)
        state.tele.user.throttle = limitedThrottle(Math.max(Math.min(Math.sin(radian)/70*distance , 1), -1))

        if (state.tele.user.throttle < .001) {
          state.tele.user.angle = 0
        }

      });
    }

    var updateUI = function() {
      $("#throttleInput").val(state.tele.user.throttle);
      $("#angleInput").val(state.tele.user.angle);
      $('#mode_select').val(state.driveMode);

      var throttlePercent = Math.round(Math.abs(state.tele.user.throttle) * 100) + '%';
      var steeringPercent = Math.round(Math.abs(state.tele.user.angle) * 100) + '%';
      var throttleRounded = state.tele.user.throttle.toFixed(2)
      var steeringRounded = state.tele.user.angle.toFixed(2)

      $('#throttle_label').html(throttleRounded);
      $('#steering_label').html(steeringRounded);

      if(state.tele.user.throttle < 0) {
        $('#throttle-bar-backward').css('width', throttlePercent).html(throttleRounded)
        $('#throttle-bar-forward').css('width', '0%').html('')
      }
      else if (state.tele.user.throttle > 0) {
        $('#throttle-bar-backward').css('width', '0%').html('')
        $('#throttle-bar-forward').css('width', throttlePercent).html(throttleRounded)
      }
      else {
        $('#throttle-bar-forward').css('width', '0%').html('')
        $('#throttle-bar-backward').css('width', '0%').html('')
      }

      if(state.tele.user.angle < 0) {
        $('#angle-bar-backward').css('width', steeringPercent).html(steeringRounded)
        $('#angle-bar-forward').css('width', '0%').html('')
      }
      else if (state.tele.user.angle > 0) {
        $('#angle-bar-backward').css('width', '0%').html('')
        $('#angle-bar-forward').css('width', steeringPercent).html(steeringRounded)
      }
      else {
        $('#angle-bar-forward').css('width', '0%').html('')
        $('#angle-bar-backward').css('width', '0%').html('')
      }

      if (state.recording) {
        $('#record_button')
          .html('Stop Recording (r)')
          .removeClass('btn-info')
          .addClass('btn-warning').end()
      } else {
        $('#record_button')
          .html('Start Recording (r)')
          .removeClass('btn-warning')
          .addClass('btn-info').end()
      }

      if (state.num_records) {
        $('#record_count_label').text(state.num_records + ' records');
      } else {
        $('#record_count_label').text('');
      }

      if (state.brakeOn) {
        $('#brake_button')
          .html('Start Vehicle')
          .removeClass('btn-danger')
          .addClass('btn-success').end()
      } else {
        $('#brake_button')
          .html('Stop Vehicle')
          .removeClass('btn-success')
          .addClass('btn-danger').end()
      }

      if(deviceHasOrientation) {
        $('#tilt-toggle').removeAttr("disabled")
        $('#tilt').removeAttr("disabled")
      } else {
        $('#tilt-toggle').attr("disabled", "disabled");
        $('#tilt').prop("disabled", true);
      }

      if(hasGamepad) {
        $('#gamepad-toggle').removeAttr("disabled")
        $('#gamepad').removeAttr("disabled")
      } else {
        $('#gamepad-toggle').attr("disabled", "disabled");
        $('#gamepad').prop("disabled", true);
      }

      if (state.controlMode == "joystick") {
        $('#joystick_outer').show();
        $('#joystick-toggle').addClass("active");
        $('#joystick').attr("checked", "checked")
      } else {
        $('#joystick_outer').hide();
        $('#joystick-toggle').removeClass("active");
        $('#joystick').removeAttr("checked");
      }

      if (state.controlMode == "tilt") {
        $('#tilt-toggle').addClass("active");
        $('#tilt').attr("checked", "checked");
      } else {
        $('#tilt-toggle').removeClass("active");
        $('#tilt').removeAttr("checked")
      }

      //drawLine(state.tele.user.angle, state.tele.user.throttle)
    };

    const ALL_POST_FIELDS = ['angle', 'throttle', 'drive_mode', 'recording', 'buttons'];

    //
    // Set any changed properties to the server
    // via the websocket connection
    //
    var postDrive = function(fields=[]) {

        if(fields.length === 0) {
            fields = ALL_POST_FIELDS;
        }

        let data = {}
        fields.forEach(field => {
            switch (field) {
                case 'angle': data['angle'] = state.tele.user.angle; break;
                case 'throttle': data['throttle'] = state.tele.user.throttle; break;
                case 'drive_mode': data['drive_mode'] = state.driveMode; break;
                case 'recording': data['recording'] = state.recording; break;
                case 'buttons': data['buttons'] = state.buttons; break;
                default: console.log(`Unexpected post field: '${field}'`); break;
            }
        });
        if(data) {
            let json_data = JSON.stringify(data);
            console.log(`Posting ${json_data}`);
            socket.send(json_data)
            updateUI()
        }
    };

    var applyDeadzone = function(number, threshold){
       percentage = (Math.abs(number) - threshold) / (1 - threshold);

       if(percentage < 0)
          percentage = 0;

       return percentage * (number > 0 ? 1 : -1);
    }



    function gamePadLoop() {
      setTimeout(gamePadLoop,100);

      if (state.controlMode != "gamepad") {
        return;
      }

      var gamepads = navigator.getGamepads();

      for (var i = 0; i < gamepads.length; ++i)
        {
          var pad = gamepads[i];
          // some pads are NULL I think.. some aren't.. use one that isn't null
          if (pad && pad.timestamp!=0)
          {

            var joystickX = applyDeadzone(pad.axes[2], 0.05);

            var joystickY = applyDeadzone(pad.axes[1], 0.15);

            state.tele.user.angle = joystickX;
            state.tele.user.throttle = limitedThrottle((joystickY * -1));

            if (state.tele.user.throttle == 0 && state.tele.user.throttle == 0) {
              state.brakeOn = true;
            } else {
              state.brakeOn = false;
            }

            if (state.tele.user.throttle != 0) {
              state.recording = true;
            } else {
              state.recording = false;
            }

            postDrive()

          }
            // todo; simple demo of displaying pad.axes and pad.buttons
        }
      }


    // Send control updates to the server every .1 seconds.
    function joystickLoop () {
       setTimeout(function () {
            postDrive()

          if (joystickLoopRunning && state.controlMode == "joystick") {
             joystickLoop();
          }
       }, 100)
    }

    // Control throttle and steering with device orientation
    function handleOrientation(event) {

      var alpha = event.alpha;
      var beta = event.beta;
      var gamma = event.gamma;

      if (beta == null || gamma == null) {
        deviceHasOrientation = false;
        state.controlMode = "joystick";
        console.log("Invalid device orientation values, switched to joystick mode.")
      } else {
        deviceHasOrientation = true;
        console.log("device has valid orientation values")
      }

      updateUI();

      if(state.controlMode != "tilt" || !deviceHasOrientation || state.brakeOn){
        return;
      }

      if(!initialGamma && gamma) {
        initialGamma = gamma;
      }

      var newThrottle = gammaToThrottle(gamma);
      var newAngle = betaToSteering(beta, gamma);

      // prevent unexpected switch between full forward and full reverse
      // when device is parallel to ground
      if (state.tele.user.throttle > 0.9 && newThrottle <= 0) {
        newThrottle = 1.0
      }

      if (state.tele.user.throttle < -0.9 && newThrottle >= 0) {
        newThrottle = -1.0
      }

      state.tele.user.throttle = limitedThrottle(newThrottle);
      state.tele.user.angle = newAngle;
    }

    function deviceOrientationLoop () {
       setTimeout(function () {
          if(!state.brakeOn){
            postDrive()
          }

          if (state.controlMode == "tilt") {
            deviceOrientationLoop();
          }
       }, 100)
    }

    var throttleUp = function(){
      state.tele.user.throttle = limitedThrottle(Math.min(state.tele.user.throttle + .05, 1));
      postDrive()
    };

    var throttleDown = function(){
      state.tele.user.throttle = limitedThrottle(Math.max(state.tele.user.throttle - .05, -1));
      postDrive()
    };

    var angleLeft = function(){
      state.tele.user.angle = Math.max(state.tele.user.angle - .1, -1)
      postDrive()
    };

    var angleRight = function(){
      state.tele.user.angle = Math.min(state.tele.user.angle + .1, 1)
      postDrive()
    };

    var updateDriveMode = function(mode){
      state.driveMode = mode;
      postDrive(["drive_mode"])
    };

    var toggleDriveMode = function() {
      switch(state.driveMode) {
        case "user": {
            updateDriveMode("local_angle");
            break;
        }
        case "local_angle": {
            updateDriveMode("local");
            break;
        }
        default: {
            updateDriveMode("user");
            break;
        }
      }
    }

    var toggleRecording = function(){
      state.recording = !state.recording
      postDrive(['recording']);
    };

    var toggleBrake = function(){
      state.brakeOn = !state.brakeOn;
      initialGamma = null;

      if (state.brakeOn) {
        brake();
      }
    };

    var brake = function(i){
          console.log('post drive: ' + i)
          state.tele.user.angle = 0
          state.tele.user.throttle = 0
          state.recording = false
          state.driveMode = 'user';
          postDrive()

      i++
      if (i < 5) {
        setTimeout(function () {
          console.log('calling brake:' + i)
          brake(i);
        }, 500)
      };

      state.brakeOn = true;
      updateUI();
    };

    var limitedThrottle = function(newThrottle){
      var limitedThrottle = 0;

      if (newThrottle > 0) {
        limitedThrottle = Math.min(state.maxThrottle, newThrottle);
      }

      if (newThrottle < 0) {
        limitedThrottle = Math.max((state.maxThrottle * -1), newThrottle);
      }

      if (state.throttleMode == 'constant') {
        limitedThrottle = state.maxThrottle;
      }

      return limitedThrottle;
    }

    var selectedCount = function() {
      return Object.keys(reviewState.selected).filter(function(k) {
        return reviewState.selected[k];
      }).length;
    };

    var openReviewDrawer = function() {
      // Pause recording so deletes don't race the writer
      if (state.recording) {
        state.recording = false;
        postDrive(['recording']);
        updateUI();
      }
      reviewState.open = true;
      $('#review_drawer').addClass('open').attr('aria-hidden', 'false');
      $('body').addClass('review-open');
      loadRecentRecords();
    };

    var closeReviewDrawer = function() {
      reviewState.open = false;
      $('#review_drawer').removeClass('open').attr('aria-hidden', 'true');
      $('body').removeClass('review-open');
    };

    var updateReviewControls = function() {
      var n = selectedCount();
      $('#review_delete').prop('disabled', n === 0 || reviewState.loading);
      var status = '';
      if (reviewState.tubPath) {
        status = reviewState.records.length + ' shown / ' + reviewState.total + ' in tub';
        if (n > 0) {
          status += ' · ' + n + ' selected';
        }
      } else if (!reviewState.loading) {
        status = 'No tub attached — record some data first';
      }
      if (reviewState.loading) {
        status = 'Loading…';
      }
      $('#review_status').text(status);
    };

    var setReviewPreview = function(rec) {
      if (!rec) {
        $('#review_preview_img').attr('src', '');
        $('#review_preview_meta').text('Select a frame to preview');
        return;
      }
      reviewState.activeIndex = rec.index;
      $('#review_preview_img').attr('src', '/api/tub/image/' + rec.index + '?t=' + Date.now());
      $('#review_preview_meta').html(
        '<div>index: <b>' + rec.index + '</b></div>' +
        '<div>angle: ' + Number(rec.angle).toFixed(3) + '</div>' +
        '<div>throttle: ' + Number(rec.throttle).toFixed(3) + '</div>'
      );
      $('#review_grid .review-thumb').removeClass('active');
      $('#review_grid .review-thumb[data-index="' + rec.index + '"]').addClass('active');
    };

    var renderReviewGrid = function() {
      var $grid = $('#review_grid');
      $grid.empty();
      if (!reviewState.records.length) {
        $grid.html('<div class="review-empty">No recent records to show. Drive and record, then refresh.</div>');
        setReviewPreview(null);
        updateReviewControls();
        return;
      }

      reviewState.records.forEach(function(rec) {
        var selected = !!reviewState.selected[rec.index];
        var $btn = $('<button type="button" class="review-thumb"></button>');
        $btn.attr('data-index', rec.index);
        if (selected) {
          $btn.addClass('selected');
        }
        if (reviewState.activeIndex === rec.index) {
          $btn.addClass('active');
        }
        $btn.append($('<img>').attr('src', '/api/tub/image/' + rec.index).attr('alt', '#' + rec.index));
        $btn.append($('<span class="idx"></span>').text(rec.index));
        $grid.append($btn);
      });

      if (reviewState.activeIndex == null) {
        setReviewPreview(reviewState.records[reviewState.records.length - 1]);
      } else {
        var stillThere = reviewState.records.some(function(r) {
          return r.index === reviewState.activeIndex;
        });
        if (!stillThere) {
          setReviewPreview(reviewState.records[reviewState.records.length - 1]);
        } else {
          // refresh active highlight without reloading preview image
          $('#review_grid .review-thumb').removeClass('active');
          $('#review_grid .review-thumb[data-index="' + reviewState.activeIndex + '"]').addClass('active');
        }
      }
      updateReviewControls();
    };

    // Event delegation so selection toggles don't rebuild/reload images
    $(document).on('click', '#review_grid .review-thumb', function(e) {
      var index = parseInt($(this).attr('data-index'), 10);
      var rec = null;
      for (var i = 0; i < reviewState.records.length; i++) {
        if (reviewState.records[i].index === index) {
          rec = reviewState.records[i];
          break;
        }
      }
      if (!rec) {
        return;
      }
      if (reviewState.selected[index]) {
        delete reviewState.selected[index];
        $(this).removeClass('selected');
      } else {
        reviewState.selected[index] = true;
        $(this).addClass('selected');
      }
      setReviewPreview(rec);
      updateReviewControls();
    });

    var loadRecentRecords = function() {
      var n = parseInt($('#review_n_select').val(), 10) || 100;
      reviewState.loading = true;
      updateReviewControls();
      $.getJSON('/api/tub/recent?n=' + n)
        .done(function(data) {
          reviewState.loading = false;
          if (!data || !data.ok) {
            reviewState.records = [];
            reviewState.total = 0;
            reviewState.tubPath = null;
            $('#review_status').text((data && data.error) || 'Failed to load records');
            renderReviewGrid();
            return;
          }
          reviewState.records = data.records || [];
          reviewState.total = data.total || 0;
          reviewState.tubPath = data.tub_path;
          // Drop selections that no longer exist
          var alive = {};
          reviewState.records.forEach(function(r) { alive[r.index] = true; });
          Object.keys(reviewState.selected).forEach(function(k) {
            if (!alive[k]) {
              delete reviewState.selected[k];
            }
          });
          if (typeof data.total === 'number' && data.total > 0) {
            state.num_records = data.total;
            updateUI();
          }
          renderReviewGrid();
        })
        .fail(function(xhr) {
          reviewState.loading = false;
          reviewState.records = [];
          $('#review_status').text('Failed to load: ' + (xhr.responseText || xhr.status));
          renderReviewGrid();
        });
    };

    var deleteSelectedRecords = function() {
      var indexes = Object.keys(reviewState.selected)
        .filter(function(k) { return reviewState.selected[k]; })
        .map(function(k) { return parseInt(k, 10); });
      if (!indexes.length) {
        return;
      }
      if (!window.confirm('Delete ' + indexes.length + ' selected record(s)? This marks them deleted in the tub (can be restored later via donkey ui).')) {
        return;
      }
      reviewState.loading = true;
      updateReviewControls();
      $.ajax({
        type: 'POST',
        url: '/api/tub/delete',
        contentType: 'application/json',
        dataType: 'json',
        data: JSON.stringify({ indexes: indexes }),
      })
        .done(function(data) {
          reviewState.loading = false;
          if (!data || !data.ok) {
            alert((data && data.error) || 'Delete failed');
            updateReviewControls();
            return;
          }
          reviewState.selected = {};
          if (typeof data.total === 'number') {
            state.num_records = data.total;
            updateUI();
          }
          loadRecentRecords();
        })
        .fail(function(xhr) {
          reviewState.loading = false;
          var msg = 'Delete failed';
          try {
            var parsed = JSON.parse(xhr.responseText);
            if (parsed && parsed.error) {
              msg = parsed.error;
            }
          } catch (e) {}
          alert(msg);
          updateReviewControls();
        });
    };


    // var drawLine = function(angle, throttle) {
    //
    //   throttleConstant = 100
    //   throttle = throttle * throttleConstant
    //   angleSign = Math.sign(angle)
    //   angle = toRadians(Math.abs(angle*90))
    //
    //   var canvas = document.getElementById("angleView"),
    //   context = canvas.getContext('2d');
    //   context.clearRect(0, 0, canvas.width, canvas.height);
    //
    //   base={'x':canvas.width/2, 'y':canvas.height}
    //
    //   pointX = Math.sin(angle) * throttle * angleSign
    //   pointY = Math.cos(angle) * throttle
    //   xPoint = {'x': pointX + base.x, 'y': base.y - pointY}
    //
    //   context.beginPath();
    //   context.moveTo(base.x, base.y);
    //   context.lineTo(xPoint.x, xPoint.y);
    //   context.lineWidth = 5;
    //   context.strokeStyle = '#ff0000';
    //   context.stroke();
    //   context.closePath();
    //
    // };

    var betaToSteering = function(beta, gamma) {
      const deadZone = 5;
      var angle = 0.0;
      var outsideDeadZone = false;
      var controlDirection = (Math.sign(initialGamma) * -1)

      //max steering angle at device 35º tilt
      var fullLeft = -35.0;
      var fullRight = 35.0;

      //handle beta 90 to 180 discontinuous transition at gamma 90
      if (beta > 90) {
        beta = (beta - 180) * Math.sign(gamma * -1) * controlDirection
      } else if (beta < -90) {
        beta = (beta + 180) * Math.sign(gamma * -1) * controlDirection
      }

      // set the deadzone for neutral sterring
      if (Math.abs(beta) > 90) {
        outsideDeadZone = Math.abs(beta) < 180 - deadZone;
      }
      else {
        outsideDeadZone = Math.abs(beta) > deadZone;
      }

      if (outsideDeadZone && beta < -90.0) {
        angle = remap(beta, fullLeft, (-180.0 + deadZone), -1.0, 0.0);
      }
      else if (outsideDeadZone && beta > 90.0) {
        angle = remap(beta, (180.0 - deadZone), fullRight, 0.0, 1.0);
      }
      else if (outsideDeadZone && beta < 0.0) {
        angle = remap(beta, fullLeft, 0.0 - deadZone, -1.0, 0);
      }
      else if (outsideDeadZone && beta > 0.0) {
        angle = remap(beta, 0.0 + deadZone, fullRight, 0.0, 1.0);
      }

      // set full turn if abs(angle) > 1
      if (angle < -1) {
        angle = -1;
      } else if (angle > 1) {
        angle = 1;
      }

      return angle * controlDirection;
    };

    var gammaToThrottle = function(gamma) {
      var throttle = 0.0;
      var gamma180 = gamma + 90;
      var initialGamma180 = initialGamma + 90;
      var controlDirection = (Math.sign(initialGamma) * -1);

      // 10 degree deadzone around the initial position
      // 45 degrees of motion for forward and reverse
      var minForward = Math.min((initialGamma180 + (5 * controlDirection)), (initialGamma180 + (50 * controlDirection)));
      var maxForward = Math.max((initialGamma180 + (5 * controlDirection)), (initialGamma180 + (50 * controlDirection)));
      var minReverse = Math.min((initialGamma180 - (50 * controlDirection)), (initialGamma180 - (5 * controlDirection)));
      var maxReverse = Math.max((initialGamma180 - (50 * controlDirection)), (initialGamma180 - (5 * controlDirection)));

      //constrain control input ranges to 0..180 continuous range
      minForward = Math.max(minForward, 0);
      maxForward = Math.min(maxForward, 180);
      minReverse = Math.max(minReverse, 0);
      maxReverse = Math.min(maxReverse, 180);

      if(gamma180 > minForward && gamma180 < maxForward) {
        // gamma in forward range
        if (controlDirection == -1) {
          throttle = remap(gamma180, minForward, maxForward, 1.0, 0.0);
        } else {
          throttle = remap(gamma180, minForward, maxForward, 0.0, 1.0);
        }
      } else if (gamma180 > minReverse && gamma180 < maxReverse) {
        // gamma in reverse range
        if (controlDirection == -1) {
          throttle = remap(gamma180, minReverse, maxReverse, 0.0, -1.0);
        } else  {
          throttle = remap(gamma180, minReverse, maxReverse, -1.0, 0.0);
        }
      }

      return throttle;
    };

}();


function toRadians (angle) {
  return angle * (Math.PI / 180);
}

function remap( x, oMin, oMax, nMin, nMax ){
  //range check
  if (oMin == oMax){
      console.log("Warning: Zero input range");
      return None;
  };

  if (nMin == nMax){
      console.log("Warning: Zero output range");
      return None
  }

  //check reversed input range
  var reverseInput = false;
  oldMin = Math.min( oMin, oMax );
  oldMax = Math.max( oMin, oMax );
  if (oldMin != oMin){
      reverseInput = true;
  }

  //check reversed output range
  var reverseOutput = false;
  newMin = Math.min( nMin, nMax )
  newMax = Math.max( nMin, nMax )
  if (newMin != nMin){
      reverseOutput = true;
  };

  var portion = (x-oldMin)*(newMax-newMin)/(oldMax-oldMin)
  if (reverseInput){
      portion = (oldMax-x)*(newMax-newMin)/(oldMax-oldMin);
  };

  var result = portion + newMin
  if (reverseOutput){
      result = newMax - portion;
  }

return result;
}

